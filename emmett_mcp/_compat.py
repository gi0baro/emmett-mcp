try:
    from emmett import abort, current, url
    from emmett.app import AppModule
    from emmett.tools.stream import SSEPipe

    _is_emmett = True
except ImportError:
    _is_emmett = False
    from emmett55 import abort, current, url
    from emmett55.app import AppModule
    from emmett55.tools.pipes import SSEPipe
