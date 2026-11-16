document.addEventListener('click', function (e) {
  var b = e.target.closest('button[data-copy]');
  if (!b) return;
  var text = b.getAttribute('data-copy');
  function done(ok) {
    b.textContent = ok ? 'Copied ✓' : 'Select the code and copy it';
    if (ok) b.classList.add('done');
  }
  function fallback() {
    var t = document.createElement('textarea');
    t.value = text;
    t.setAttribute('readonly', '');
    t.style.position = 'fixed';
    t.style.opacity = '0';
    document.body.appendChild(t);
    t.select();
    t.setSelectionRange(0, text.length);
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    document.body.removeChild(t);
    done(ok);
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
  } else {
    fallback();
  }
});

// Pairing is a transition into the feed, not a destination in Back history.
document.addEventListener('submit', async function (e) {
  var form = e.target;
  if (!form.matches('form[action="/pair/code"]')) return;
  e.preventDefault();
  if (form.dataset.submitting) return;
  form.dataset.submitting = 'true';
  var button = form.querySelector('button');
  if (button) button.disabled = true;
  var error = form.querySelector('[role="alert"]');
  if (error) error.remove();
  try {
    var response = await fetch('/pair/code', { method: 'POST', credentials: 'same-origin' });
    if (!response.ok) throw new Error('pairing request failed');
    window.location.replace('/pair/wait');
  } catch (err) {
    error = document.createElement('p');
    error.setAttribute('role', 'alert');
    error.textContent = 'Could not get a pairing code. Try again.';
    form.appendChild(error);
  } finally {
    delete form.dataset.submitting;
    if (button) button.disabled = false;
  }
});

if (document.querySelector('[data-pair-wait]')) {
  setTimeout(function () { window.location.replace('/pair/wait'); }, 3000);
}

// A browser may restore a previous document without asking the server. Recheck the
// cookie: an already paired device is redirected to the feed rather than shown a code.
window.addEventListener('pageshow', function (e) {
  if (e.persisted) window.location.replace('/pair/wait');
});
