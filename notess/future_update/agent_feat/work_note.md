PLAYING → PAUSED → PLAYING (resume)
         → STOPPED → PLAYING (restart from beginning)

1. audio_controller.py — add pause/resume:
`python
def pause(self):
    if self.player:
        self.player.pause()  # VLC toggles pause with this
        
def resume(self):
    if self.player:
        self.player.play()

def is_paused(self):
    if self.player:
        import vlc
        return self.player.get_state() == vlc.State.Paused
    return False
`

2. playback_controller.py 
`python
def pause(self):
    if self.audio_controller:
        self.audio_controller.pause()

def resume(self):
    if self.audio_controller:
        self.audio_controller.resume()
`

3. playlist_engine.py — add pause/resume without losing position:
`python
def pause(self):
    # pause VLC but keep engine state intact
    self.playback_controller.pause()
    self._is_paused = True

def resume(self):
    self.playback_controller.resume()
    self._is_paused = False
`

4. local_agent_api.py — add endpoints:
`python
@app.route('/pause', methods=['POST'])
def pause():
    if agent:
        agent.playback_controller.pause()
    return "OK"

@app.route('/resume', methods=['POST'])
def resume():
    if agent:
        agent.playback_controller.resume()
    return "OK"
`

5. tray_app.py — the button toggles based on state:
`python
def toggle_playback(self):
    try:
        r = requests.get(self.api_url + "/status", timeout=2)
        status = r.json().get("status")
        
        if status == "PLAYING":
            requests.post(self.api_url + "/pause")
        elif status == "PAUSED":
            requests.post(self.api_url + "/resume")
        else:
            # IDLE or STOPPED — restart playlist from beginning
            requests.post(self.api_url + "/playlist/start")
    except Exception:
        pass
`

