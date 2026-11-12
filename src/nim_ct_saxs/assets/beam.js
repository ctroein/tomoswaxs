/* Latest-position-only beam input. No hover RPCs, no unbounded event queue. */
(() => {
  let active = null;
  function enqueue(event, finished) {
    const rect = active.element.getBoundingClientRect();
    const position = [(event.clientX - rect.left) / rect.width,
               (event.clientY - rect.top) / rect.height, finished, active.shortcut];
    active.last = event;
    window.nimUpdates.submit('beam',position,finished);
  }

  document.addEventListener('pointerdown', (event) => {
    const viewport = event.target.closest('#volume-interaction');
    const shortcut = !!(event.altKey && event.shiftKey && !event.ctrlKey && !event.metaKey);
    if (!viewport || !shortcut || event.button !== 0) return;
    window.nimCoordinates?.pause();
    const element = viewport;
    event.preventDefault();
    event.stopImmediatePropagation();
    // Latch the selected operation until pointer release, even if modifiers
    // are released first.
    active = { element, pointer: event.pointerId, last: event, shortcut };
    element.setPointerCapture(event.pointerId);
    enqueue(event, false);
  }, true);
  document.addEventListener('pointermove', (event) => {
    if (!active || active.pointer !== event.pointerId) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    enqueue(event, false);
  }, true);
  function finish(event) {
    if (!active || active.pointer !== event.pointerId) return;
    event.stopImmediatePropagation();
    enqueue(event.type === 'lostpointercapture' ? active.last : event, true);
    active = null;
  }
  document.addEventListener('pointerup', finish, true);
  document.addEventListener('pointercancel', finish, true);
  document.addEventListener('lostpointercapture', finish, true);
})();
