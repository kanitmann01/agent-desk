// Applies the stored desk theme before the first paint, so a page never
// flashes the default theme first. Loaded as a plain blocking script in
// <head> (the CSP allows scripts from 'self' only, never inline).
(function () {
  var themes = { unkey: 1, coforge: 1, momentuum: 1 };
  var id = 'unkey';
  try {
    var stored = window.localStorage.getItem('agentdesk.theme');
    if (stored && Object.prototype.hasOwnProperty.call(themes, stored)) id = stored;
  } catch (e) {
    // Storage unavailable: the default theme.
  }
  document.documentElement.setAttribute('data-theme', id);
})();
