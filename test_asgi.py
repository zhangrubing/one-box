import asyncio
from backend.app import app
import httpx


async def main():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as c:
        r = await c.get('/login')
        print('GET /login', r.status_code)

        r = await c.get('/')
        print('GET /', r.status_code, r.headers.get('location'))

        r = await c.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
        print('POST /api/login', r.status_code, r.text[:120])
        cookies = r.cookies

        r = await c.get('/', cookies=cookies, follow_redirects=False)
        print('GET / (after login)', r.status_code, r.headers.get('location'))

        r = await c.get('/dashboard', cookies=cookies)
        print('GET /dashboard', r.status_code)

        # admin-only sections
        r = await c.get('/operations', cookies=cookies)
        print('GET /operations', r.status_code)
        r = await c.post('/api/ops/run?cmd=uptime', json={}, cookies=cookies)
        print('POST /api/ops/run?cmd=uptime', r.status_code)
        r = await c.get('/audit', cookies=cookies)
        print('GET /audit', r.status_code)
        r = await c.get('/api/audit', cookies=cookies)
        print('GET /api/audit', r.status_code)


if __name__ == '__main__':
    asyncio.run(main())
