from pathlib import Path
import sys

class Paths:
    # Go up two parents as this is in a nested directory
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)).resolve()
    RES = BASE_DIR / "res"
    DEPS = BASE_DIR / "deps"

    @classmethod
    def deps(cls, relative_path=None):
        """Grabs from the dependencies folder by relative name.
        If no relative path is specified, it returns the /deps/ folder."""
        return cls.DEPS / relative_path if relative_path is not None else cls.DEPS

    @classmethod
    def resource(cls, relative_path=None):
        """Grabs a resource by relative name.
        If no relative path is specified, it returns the /res/ folder."""
        return cls.RES / relative_path if relative_path is not None else cls.RES

    @classmethod
    def base(cls,relative_path=None):
        """Grabs a resource from the base path.
        If no relative path is specified, it returns the base path."""
        return cls.BASE_DIR / relative_path if relative_path is not None else cls.BASE_DIR

    @classmethod
    def absolute(cls, path):
        """Return the absolute, expanded path as a Path object."""
        return Path(path).expanduser().resolve()

    @classmethod
    def sound_path(cls, filename, ui_mode):
        """For use with audio_manager.
        Prefers sonic/ paths for sonic mode.
        """
        # Eventually move this out of here so that the pathing logic has no
        # idea what ui mode it is.
        if ui_mode == "sonic":
            return Paths.resource(f"sonic/sounds/{filename}")
        # Default sounds are in the root res/ folder (e.g., res/etw.wav)
        return Paths.resource(filename)    
