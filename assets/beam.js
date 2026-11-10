/* Latest-position-only beam input. No hover RPCs, no unbounded event queue. */
(() => {
  let active = null;
  let pending = null;
  let inFlight = false;
  let timer = null;
  let lastSent = -Infinity;
  const interval = 100;

  async function pump() {
    if (inFlight || !pending) return;
    clearTimeout(timer);
    const delay = interval - (performance.now() - lastSent);
    if (!pending[2] && delay > 0) {
      timer = setTimeout(pump, delay);
      return;
    }
    const position = pending;
    pending = null;
    inFlight = true;
    lastSent = performance.now();
    try {
      await window.trame.trigger('nim_beam_position', position);
    } catch (error) {
      console.error('Beam update failed', error);
      pending = null;
    } finally {
      inFlight = false;
      pump();
    }
  }

  function enqueue(event, finished) {
    const rect = active.element.getBoundingClientRect();
    pending = [(event.clientX - rect.left) / rect.width,
               (event.clientY - rect.top) / rect.height, finished];
    active.last = event;
    pump();
  }

  document.addEventListener('pointerdown', (event) => {
    const element = event.target.closest('#beam-drag-overlay');
    if (!element || event.button !== 0) return;
    event.preventDefault();
    active = { element, pointer: event.pointerId, last: event };
    element.setPointerCapture(event.pointerId);
    enqueue(event, false);
  });
  document.addEventListener('pointermove', (event) => {
    if (!active || active.pointer !== event.pointerId) return;
    enqueue(event, false);
  });
  function finish(event) {
    if (!active || active.pointer !== event.pointerId) return;
    enqueue(event.type === 'lostpointercapture' ? active.last : event, true);
    active = null;
  }
  document.addEventListener('pointerup', finish);
  document.addEventListener('pointercancel', finish);
  document.addEventListener('lostpointercapture', finish);
})();
