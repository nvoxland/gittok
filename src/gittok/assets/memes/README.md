# Bundled meme assets

Default images and layouts come from memegen at the revision in SOURCES.json.
That manifest records hashes for each upstream file. GitTok draws card text
locally with Pillow; it does not send card contents to an image service.

LICENSE.txt is the upstream project notice. Template configs retain upstream
metadata and source links; original images belong to their respective creators.
The bundled fonts are Titillium Web Black/SemiBold, Kalam Regular, and Noto Sans
Bold. Font notices are included in fonts/*-OFL.txt along with upstream notices.

Refresh using scripts/vendor_memes.py from a GitTok source checkout. Runtime
rendering reads these assets directly; user downloads override them.
