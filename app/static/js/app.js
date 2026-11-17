// Move focus to the first error/alert so screen-reader and keyboard users land on it.
(function () {
  var el = document.querySelector('[data-focus]');
  if (el) { if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1'); el.focus(); }
})();
