"""Small WebDriver BiDi client for the installed Firefox; no production dependency."""
import json
import time
import websocket

class Browser:
    def __init__(self, port=19228, accept_insecure=True, basic_auth=None):
        self.socket = websocket.create_connection(f"ws://127.0.0.1:{port}/session", timeout=30, suppress_origin=True, http_no_proxy=["127.0.0.1", "localhost"])
        self.counter = 0
        self.created_contexts = []
        self.user_contexts = []
        self.basic_auth = basic_auth
        self.call("session.new", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": accept_insecure}}})
        if basic_auth:
            self.call('session.subscribe', {'events': ['network.authRequired']})
            self.call('network.addIntercept', {'phases': ['authRequired']})
    def call(self, method, params):
        self.counter += 1
        number=self.counter
        self.socket.send(json.dumps({"id": number, "method": method, "params": params}))
        while True:
            result=json.loads(self.socket.recv())
            if result.get('method') == 'network.authRequired' and self.basic_auth:
                event = result['params']
                params = {'request': event['request']['request'], 'action': 'cancel'}
                if event['request']['url'].startswith(self.basic_auth['origin'] + '/'):
                    params.update(action='provideCredentials', credentials={
                        'type': 'password', 'username': self.basic_auth['username'], 'password': self.basic_auth['password']})
                self.counter += 1
                self.socket.send(json.dumps({'id': self.counter, 'method': 'network.continueWithAuth', 'params': params}))
                continue
            if result.get("id") == number:
                if result.get("type") == "error":
                    raise RuntimeError(f"{method}: {result.get('error')} {result.get('message')}")
                return result.get("result", {})
    def context(self, private=False):
        params={"type": "tab"}
        if private:
            params["userContext"]=self.call("browser.createUserContext",{})["userContext"]
            self.user_contexts.append(params["userContext"])
        context=self.call("browsingContext.create",params)["context"]
        self.created_contexts.append(context)
        return context
    def evaluate(self, context, expression):
        result=self.call("script.evaluate", {"expression":f"(async () => JSON.stringify(await ({expression})))()", "target":{"context":context}, "awaitPromise":True})
        if result.get("type") == "exception":
            raise RuntimeError(result.get("exceptionDetails",{}).get("text", "JavaScript failed"))
        value=result.get("result",{}).get("value")
        return json.loads(value) if value is not None else None
    def wait(self, context, expression, timeout=15):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            if self.evaluate(context,expression):return
            time.sleep(.08)
        raise AssertionError("Browser condition timed out: "+expression[:100])
    def navigate(self, context, url):
        self.call("browsingContext.navigate",{"context":context,"url":url,"wait":"complete"})
    def viewport(self, context, width, height=1000):
        self.call("browsingContext.setViewport",{"context":context,"viewport":{"width":width,"height":height},"devicePixelRatio":1})
    def click(self, context, selector):
        self.evaluate(context,'document.querySelector('+json.dumps(selector)+').scrollIntoView({block:"center"})')
        point=self.evaluate(context,'(()=>{const r=document.querySelector('+json.dumps(selector)+').getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()')
        self.call("input.performActions",{"context":context,"actions":[{"type":"pointer","id":"mouse","parameters":{"pointerType":"mouse"},"actions":[{"type":"pointerMove","x":point["x"],"y":point["y"],"origin":"viewport"},{"type":"pointerDown","button":0},{"type":"pointerUp","button":0}]}]})
    def screenshot(self, context, path):
        import base64
        result=self.call("browsingContext.captureScreenshot",{"context":context,"origin":"document"})
        path.write_bytes(base64.b64decode(result["data"]))
    def close(self):
        try:
            for context in self.created_contexts:
                self.call("browsingContext.close", {"context":context})
            for context in self.user_contexts:
                self.call("browser.removeUserContext", {"userContext":context})
            self.call("session.end", {})
        finally:
            self.socket.close()
