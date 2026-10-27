/* Opt-in DevTools helper. No field values, identifiers, cookies or network calls. */
(() => {
  window.CompassScenario?.cancel();
  const allowed = new Set(['login', 'self_report', 'view_history', 'assistant_message', 'doctor_notification']);
  let state = null;
  const click = () => { if (state) state.activations++; };
  const change = () => { if (state) state.changes++; };
  function cancel() {
    document.removeEventListener('click', click, true);
    document.removeEventListener('change', change, true);
    state = null;
  }
  window.CompassScenario = {
    cancel,
    start(scenario) {
      if (!allowed.has(scenario)) throw new Error('Unknown scenario');
      cancel();
      state = {scenario, started: performance.now(), activations: 0, changes: 0};
      document.addEventListener('click', click, true);
      document.addEventListener('change', change, true);
    },
    stop() {
      if (!state) throw new Error('Start a scenario first');
      const ua = navigator.userAgent;
      const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : 'other';
      const result = {scenario: state.scenario, duration_ms: Math.round(performance.now() - state.started),
        activation_count: state.activations, field_change_count: state.changes,
        viewport_width: innerWidth, viewport_height: innerHeight, browser};
      cancel();
      console.log(JSON.stringify(result));
      return result;
    }
  };
})();
