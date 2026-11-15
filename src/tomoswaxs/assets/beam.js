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

  function down(event) {
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
  }
  function move(event) {
    if (!active || active.pointer !== event.pointerId) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    enqueue(event, false);
  }
  function finish(event) {
    if (!active || active.pointer !== event.pointerId) return;
    event.stopImmediatePropagation();
    enqueue(event.type === 'lostpointercapture' ? active.last : event, true);
    active = null;
  }
  const documents = new WeakMap();
  function attach(doc) {
    if (documents.has(doc)) return documents.get(doc);
    const handlers={pointerdown:down,pointermove:move,pointerup:finish,pointercancel:finish,lostpointercapture:finish};
    for(const [name,handler] of Object.entries(handlers)) doc.addEventListener(name,handler,true);
    const detach=()=>{
      if(active?.element.ownerDocument === doc) finish(active.last);
      for(const [name,handler] of Object.entries(handlers)) doc.removeEventListener(name,handler,true);
      documents.delete(doc);
    };
    documents.set(doc,detach);
    return detach;
  }
  window.nimBeam={attach};
  attach(document);
})();
