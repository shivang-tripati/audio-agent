# hooks/vlc_runtime_hook.py
import os
import sys

if getattr(sys, 'frozen', False):
    base = os.path.dirname(sys.executable)
    vlc_dir = os.path.join(base, 'vlc')
    plugins_dir = os.path.join(vlc_dir, 'plugins')
    
    os.environ['VLC_PLUGIN_PATH'] = plugins_dir
    os.environ['PATH'] = vlc_dir + os.pathsep + os.environ.get('PATH', '')
    
    # Delete stale cache so VLC rebuilds it cleanly
    cache_file = os.path.join(vlc_dir, 'plugins.dat')
    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
        except Exception:
            pass