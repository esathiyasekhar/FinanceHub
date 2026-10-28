"""Minimal tkinter stand-in to drive the setup wizard's code paths in tests (no display)."""
TclError = Exception
ALL = []
AFTER = []


class Var:
    def __init__(self, value=None):
        self.v = value

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


StringVar = BooleanVar = Var


class Widget:
    def __init__(self, master=None, **kw):
        self.kw = dict(kw)
        self.children = []
        self.master = master
        self.states = set()
        if master is not None and hasattr(master, 'children'):
            master.children.append(self)
        ALL.append(self)

    def __setitem__(self, k, v):
        self.kw[k] = v

    def __getitem__(self, k):
        return self.kw.get(k)

    def pack(self, *a, **k):
        return self

    def winfo_children(self):
        return list(self.children)

    def destroy(self):
        if self.master is not None and self in getattr(self.master, 'children', []):
            self.master.children.remove(self)

    def state(self, s):
        for x in s:
            if x.startswith('!'):
                self.states.discard(x[1:])
            else:
                self.states.add(x)

    def insert(self, *a):
        self.kw.setdefault('text_content', []).append(a[-1])

    def see(self, *a):
        pass

    def start(self, *a):
        pass

    def stop(self, *a):
        pass

    def title(self, *a):
        pass

    def geometry(self, *a):
        pass

    def resizable(self, *a):
        pass

    def iconbitmap(self, *a):
        raise TclError('no icon in tests')

    def after(self, ms, fn):
        AFTER.append(fn)

    def mainloop(self):
        pass

    def withdraw(self):
        pass


Tk = Frame = Label = Text = Widget
