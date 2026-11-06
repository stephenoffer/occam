from api.search import search

ROUTES = {"/search": search}


def handle(path, *args):
    return ROUTES[path](*args)
