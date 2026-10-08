"""UE's analytic neutral film response and fixed inverse; no GPU LUTs."""


class UEFilmCurve:
    def __init__(self, parameters=None):
        from ue_local_exposure import UEParameters
        self.parameters = parameters or UEParameters()

    def bindings(self):
        p = self.parameters
        return dict(filmSlope=p.film_slope, filmToe=p.film_toe,
                    filmShoulder=p.film_shoulder, filmBlackClip=p.film_black_clip,
                    filmWhiteClip=p.film_white_clip)
