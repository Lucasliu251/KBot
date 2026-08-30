import aiohttp


class VoiceRequestor:
    def __init__(self, token):
        self.token = token
        self.session = None

    async def _session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={'Authorization': f'Bot {self.token}'},
            )
        return self.session

    async def request(self, method, api, **kwargs):
        session = await self._session()
        async with session.request(method, f'https://www.kookapp.cn/api/v3/{api}', **kwargs) as res:
            resj = await res.json()
        if resj['code'] != 0:
            raise RuntimeError(resj['message'])
        return resj['data']

    async def join(self, cid):
        return await self.request('POST', 'voice/join', json={'channel_id': cid})

    async def leave(self, cid):
        return await self.request('POST', 'voice/leave', json={'channel_id': cid})

    async def list(self):
        return await self.request('GET', 'voice/list')

    async def keep_alive(self, cid):
        return await self.request('POST', 'voice/keep-alive', json={'channel_id': cid})

    async def close(self):
        if self.session is not None and not self.session.closed:
            await self.session.close()
