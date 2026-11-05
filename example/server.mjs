import http from 'node:http';
const ITEMS = new Map([['1', { id: '1', name: 'lamp' }]]);
export function createItemServer() {
  return http.createServer((req, res) => {
    const url = new URL(req.url || '/', 'http://127.0.0.1');
    const m = /^\/items\/([^/]+)$/u.exec(url.pathname);
    res.setHeader('content-type', 'application/json');
    if (!m || req.method !== 'GET') { res.writeHead(404); return res.end(JSON.stringify({ error: 'not found' })); }
    const id = m[1];
    if (!/^[1-9][0-9]*$/u.test(id)) { res.writeHead(400); return res.end(JSON.stringify({ error: 'id must be a positive integer' })); }
    const item = ITEMS.get(id);
    if (!item) { res.writeHead(404); return res.end(JSON.stringify({ error: 'item not found' })); }
    res.writeHead(200); res.end(JSON.stringify(item));
  });
}
