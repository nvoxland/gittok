"""Short-lived model worker. Model/MLX imports happen only after the first request.

One JSON request and response per image; the model stays loaded until stdin closes
or no request arrives within the idle grace. Only this process owns GPU allocations.
"""

import gc
import importlib
import json
import os
import select
import sys

# Public model classes, imported lazily so only the selected family is loaded.
MODELS = (
    ("z-image", "mflux.models.z_image", "ZImage"),
    ("flux2", "mflux.models.flux2", "Flux2Klein"),
    ("flux3", "mflux.models.flux3", "Flux3Klein"),
    ("qwen", "mflux.models.qwen.variants.txt2img.qwen_image", "QwenImage"),
    ("", "mflux.models.flux.variants.txt2img.flux", "Flux1"),
)


def _module_of(name):
    _, module, cls = next(item for item in MODELS if name.startswith(item[0]))
    return module, cls


def check(name):
    """None when everything `load_backend` imports for model `name` imports, else why not.
    No weights are loaded."""
    try:
        for module, attr in (
            _module_of(name),
            ("mflux.callbacks.instances.memory_saver", "MemorySaver"),
            ("mflux.models.common.config", "ModelConfig"),
        ):
            getattr(importlib.import_module(module), attr)
    except Exception as exc:  # noqa: BLE001 - any failure means the renderer cannot run
        return f"{type(exc).__name__}: {exc}"
    return None


def load_backend(request):
    import mlx.core as mx
    from mflux.callbacks.instances.memory_saver import MemorySaver
    from mflux.models.common.config import ModelConfig

    mx.clear_cache()
    name, path = request["model"], request["path"]
    model_class = getattr(importlib.import_module(_module_of(name)[0]), _module_of(name)[1])
    # `path` is a saved, pre-quantized model folder (image_model.py): no quantizing here.
    model = model_class(
        model_config=ModelConfig.from_name(model_name=path, base_model=name),
        model_path=path,
        quantize=None,
    )
    # The single-image CLI evicts the encoder and transformer. A batch needs both
    # for different later prompts; retain weights while bounding temporary caches.
    model.callbacks.register(MemorySaver(
        model=model, keep_transformer=True, keep_text_encoder=True,
        num_seeds=2, cache_limit_bytes=1000**3 if request["low_ram"] else None,
    ))

    def generate(job):
        try:
            image = model.generate_image(
                seed=job["seed"], prompt=job["prompt"], width=job["width"], height=job["height"],
                num_inference_steps=job["steps"],
            )
            image.save(path=job["output"])
            del image
        finally:
            # FLUX.1 caches embeddings per prompt. Do not accumulate them for every card.
            cache = getattr(model, "prompt_cache", None)
            if isinstance(cache, dict):
                cache.clear()
            gc.collect()
            mx.clear_cache()

    return generate


def serve(read_request, reply, *, load=load_backend):
    engine, key = None, None
    while (request := read_request()) is not None:
        try:
            new_key = tuple(request.get(k) for k in ("model", "path", "low_ram"))
            if engine is None or new_key != key:
                engine = None
                gc.collect()  # release the previous model before loading another one
                engine = load(request)
                key = new_key
            engine(request)
            reply({"ok": True})
        except Exception as exc:
            reply({"ok": False, "error": str(exc)[-4000:] or type(exc).__name__})
            return 1  # retire a failed model; the next card gets a clean batch
    return 0


def main(*, load=load_backend):
    if sys.argv[1:2] == ["--check"]:
        why = check(sys.argv[2])
        print(why or "ok", file=sys.stderr if why else sys.stdout)
        return 1 if why else 0
    idle = float(sys.argv[1])
    # Reserve stdout's pipe for protocol responses. Redirect even native-library
    # stdout writes to stderr so logging cannot corrupt the JSON stream.
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1) as protocol:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

        def read_request():
            if not select.select([sys.stdin], [], [], idle)[0]:
                return None
            line = sys.stdin.readline()
            return json.loads(line) if line else None

        return serve(read_request, lambda result: protocol.write(json.dumps(result) + "\n"),
                     load=load)


if __name__ == "__main__":
    sys.exit(main())
