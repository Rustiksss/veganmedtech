/* One origin, server sessions. This module never persists credentials. */
window.CompassAPI = (() => {
  let generation = 0;
  const pending = new Set();
  const csrf = () => document.cookie.split('; ').find(x => x.startsWith('csrftoken='))?.split('=').slice(1).join('=') || '';
  function clear() {
    generation++;
    pending.forEach(c => c.abort());
    pending.clear();
  }
  async function request(path, {method = 'GET', body, headers = {}, auth = false} = {}) {
    const version = generation;
    const controller = new AbortController();
    pending.add(controller);
    try {
      const response = await fetch(path, {
        method, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        headers: {Accept: 'application/json', ...(body ? {'Content-Type': 'application/json'} : {}),
          ...(!['GET', 'HEAD'].includes(method) ? {'X-CSRFToken': csrf()} : {}), ...headers},
        ...(body ? {body: JSON.stringify(body)} : {})
      });
      const data = await response.json().catch(() => ({}));
      if (version !== generation) throw new DOMException('Stale response', 'AbortError');
      if (!response.ok && !auth) {
        const error = new Error(data.error?.message || 'Не удалось выполнить запрос. Повторите попытку.');
        error.status = response.status;
        error.fields = data.error?.fields;
        throw error;
      }
      return auth ? {...data, status: response.status} : data;
    } finally {
      pending.delete(controller);
    }
  }
  return {request, clear, auth: (path, options = {}) => request('/_allauth/browser/v1/' + path, {...options, auth: true})};
})();
