"""WolvenKit's own code, called from Python, for every step that reads or
writes the game's file formats.

The tool loads WolvenKit's libraries (WolvenKit.Modkit.dll and the rest)
through pythonnet and calls the same functions WolvenKit's command line
calls. They come from either of two folders:

- the WolvenKit app (%LOCALAPPDATA%\\Programs\\WolvenKit), which carries its
  own .NET runtime, so nothing else needs installing
- the WolvenKit CLI (%LOCALAPPDATA%\\Programs\\WolvenKit.CLI), which needs
  the .NET runtime it was built for to be installed

What it takes:

- the services WolvenKit's command line builds through its GenericHost,
  built by hand here, since the GenericHost will not build outside its own
  process
- an ArchiveManager with the game's archives loaded, because exporting and
  importing animations look the face rig up in the game
- an .anims passed to the importer as a growable MemoryStream

Needs WolvenKit 9.1 or later, tested with the app 9.1.0 and the CLI 9.1.0.
WolvenKit 8 fails on reading a file to JSON. The importer adds the .glb's
animations to the .anims it is given; it does not drop the ones already
there, whatever its Keep option says."""
import json
import os
import re
import tempfile

APP = os.path.expandvars(r'%LOCALAPPDATA%\Programs\WolvenKit')
CLI = os.path.expandvars(r'%LOCALAPPDATA%\Programs\WolvenKit.CLI')
DEFAULT_GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Cyberpunk 2077'

_loaded = None      # the folder the runtime was started from; .NET loads once per process


def find(folder=None):
    """The WolvenKit folder to use: the one given, else the app, else the CLI."""
    for f in ([folder] if folder else [APP, CLI]):
        if f and (os.path.exists(os.path.join(f, 'WolvenKit.Modkit.dll'))):
            return f
    raise SystemExit('WolvenKit not found%s. Install the WolvenKit app, or give its folder with '
                     '--wolvenkit.' % (' in ' + folder if folder else ''))


def _start(folder):
    global _loaded
    if _loaded:
        if os.path.normcase(_loaded) != os.path.normcase(folder):
            raise RuntimeError('WolvenKit is already loaded from %s' % _loaded)
        return
    import sys
    from pythonnet import load
    # Started through the program's own entry file, as WolvenKit itself is:
    # writing JSON asks .NET for the entry assembly and fails without one.
    if os.path.exists(os.path.join(folder, 'WolvenKit.CLI.dll')):
        # The CLI uses the installed .NET, or the one DOTNET_ROOT names.
        load('coreclr', entry_dll=os.path.join(folder, 'WolvenKit.CLI.dll'),
             dotnet_root=os.environ.get('DOTNET_ROOT'))
    else:
        # The app is self-contained: its .NET runtime is in its own folder.
        load('coreclr', entry_dll=os.path.join(folder, 'WolvenKit.dll'), dotnet_root=folder)
    sys.path.append(folder)
    _loaded = folder


class WolvenKit:
    """One loaded WolvenKit, with the game's archives, for the whole run.

    With game=None it never reads the game. Give `archives` instead: the
    .archive files that hold what the steps need (for an import, the face
    rig the set names). With only the rig loaded, an import writes the same
    file, byte for byte, as with the whole game."""

    def __init__(self, folder=None, game=DEFAULT_GAME, archives=()):
        self.folder = find(folder)
        self.game = game
        self.extra_archives = list(archives)
        _start(self.folder)
        import clr
        from System import Activator, Reflection
        for n in ('WolvenKit.Core', 'WolvenKit.Common', 'WolvenKit.RED4', 'WolvenKit.Modkit'):
            clr.AddReference(os.path.join(self.folder, n + '.dll'))

        def asm(name):
            return Reflection.Assembly.LoadFrom(os.path.join(self.folder, name + '.dll'))

        def new(a, name, *args):
            return Activator.CreateInstance(a.GetType(name), *args) if args else \
                Activator.CreateInstance(a.GetType(name))

        # WolvenKit prints its own progress ("100%") to the console; the
        # tool says what it is doing itself.
        from System import Console
        from System.IO import TextWriter
        Console.SetOut(TextWriter.Null)
        core, common, modkit = asm('WolvenKit.Core'), asm('WolvenKit.Common'), asm('WolvenKit.Modkit')
        version = modkit.GetName().Version
        if (version.Major, version.Minor) < (9, 1):
            # WolvenKit 8 cannot write JSON outside its own program (its JSON
            # header needs .NET's entry assembly, which is not set here).
            raise SystemExit('WolvenKit %s found in %s; the tool needs 9.1 or later'
                             % (version, self.folder))
        self._common = common
        flags = (Reflection.BindingFlags.Public | Reflection.BindingFlags.NonPublic
                 | Reflection.BindingFlags.Instance | Reflection.BindingFlags.Static)
        tools_type = modkit.GetType('WolvenKit.Modkit.RED4.ModTools')
        logger = new(core, 'WolvenKit.SerilogWrapper')
        hash_type = common.GetType('WolvenKit.Common.Services.HashService')
        # The list of every known game file name takes about 950 MB and 7 s
        # to load. Reading scenes and lipmaps to JSON needs it for their
        # paths; importing an animation does not, so with no game it stays
        # empty: the import writes the same bytes either way.
        hashes = Activator.CreateInstance(hash_type, [self.game is not None])
        hooks = new(common, 'WolvenKit.Common.Services.HookService')
        progress = new(common, 'WolvenKit.Common.Services.PercentProgressService')
        parser = Activator.CreateInstance(common.GetType('WolvenKit.RED4.CR2W.Red4ParserService'),
                                          [hashes, logger, hooks])
        self.archives = Activator.CreateInstance(
            modkit.GetType('WolvenKit.RED4.CR2W.Archive.ArchiveManager'),
            [hashes, parser, logger, progress])
        ctor = [c for c in tools_type.GetConstructors(flags) if c.GetParameters().Length == 6][0]
        self.tools = ctor.Invoke([logger, progress, hashes, parser, self.archives, hooks])
        self._import = [m for m in tools_type.GetMethods(flags) if m.Name == 'ImportAnims'
                        and m.GetParameters()[0].ParameterType.Name == 'FileInfo'][0]
        self._extract_all = tools_type.GetMethod('ExtractAll')
        self._game_loaded = False

    def _load_game(self):
        if not self._game_loaded:
            from System.IO import FileInfo
            if self.game:
                exe = os.path.join(self.game, 'bin', 'x64', 'Cyberpunk2077.exe')
                if not os.path.exists(exe):
                    raise SystemExit('Cyberpunk 2077 not found in %s: give its folder with --game'
                                     % self.game)
                self.archives.GetType().GetMethod('LoadGameArchives').Invoke(self.archives, [FileInfo(exe)])
            for path in self.extra_archives:
                self.archives.GetType().GetMethod('LoadModArchive').Invoke(
                    self.archives, [os.path.abspath(path), False, False])
            self._game_loaded = True

    def _game_archives(self, under=None):
        """The game's archives, or those whose path is or lies under `under`."""
        self._load_game()
        out = []
        for ar in self.archives.Archives.Items:
            p = str(ar.ArchiveAbsolutePath)
            if under is None or os.path.normcase(p).startswith(os.path.normcase(under)):
                out.append(ar)
        return out

    # ---------------------------------------------------------------- files
    def read(self, path):
        """A game-format file as WolvenKit's JSON, header included."""
        return json.loads(self.tools.ConvertToJsonAsync(path, False).Result)

    def write(self, doc, path):
        """WolvenKit's JSON back into a game-format file at path."""
        from System.IO import DirectoryInfo, FileInfo
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # WolvenKit writes into a temporary folder on the same drive as the
        # file: Windows cannot move a file from one drive to another.
        with tempfile.TemporaryDirectory(dir=os.path.dirname(path), prefix='.lipsync_') as tmp:
            src = os.path.join(tmp, os.path.basename(path) + '.json')
            with open(src, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2)
            ok = self.tools.ConvertFromJsonAndWriteAsync(FileInfo(src), DirectoryInfo(tmp), None).Result
            if not ok:
                raise RuntimeError('WolvenKit could not write ' + path)
            os.replace(os.path.join(tmp, os.path.basename(path)), path)

    def export(self, path, out_dir):
        """Export one file the way WolvenKit's export does: an .anims to
        .anims.glb, a .wem to .ogg. Returns the files written."""
        from System.IO import DirectoryInfo, FileInfo
        from System import Activator
        os.makedirs(out_dir, exist_ok=True)
        self._load_game()
        before = {f: os.path.getmtime(f) for f in _files(out_dir)}
        args_ns = 'WolvenKit.Common.Model.Arguments.'
        kinds = ('XbmExportArgs', 'MeshExportArgs', 'MorphTargetExportArgs', 'MlmaskExportArgs',
                 'WemExportArgs', 'AnimationExportArgs')
        globals_ = Activator.CreateInstance(self._common.GetType(args_ns + 'GlobalExportArgs'))
        globals_.Register([Activator.CreateInstance(self._common.GetType(args_ns + k)) for k in kinds])
        f = FileInfo(path)
        if not self.tools.Export(f, globals_, f.Directory, DirectoryInfo(out_dir), None):
            raise RuntimeError('WolvenKit could not export ' + path)
        # New files, and files written over (a second export to the same place).
        return sorted(f for f in _files(out_dir) if before.get(f) != os.path.getmtime(f))

    def unbundle(self, out_dir, regex, under=None):
        """Extract the files whose depot path matches regex from the game's
        archives (those under `under` only, if given) into out_dir."""
        from System.IO import DirectoryInfo
        os.makedirs(out_dir, exist_ok=True)
        for ar in self._game_archives(under):
            self.tools.ExtractAll(ar, DirectoryInfo(out_dir), None, regex, False)
        # Only the files the regex names, not whatever else the folder holds.
        found = re.compile(regex)
        return [f for f in _files(out_dir)
                if found.search(os.path.relpath(f, out_dir).replace('/', '\\'))]

    def list(self, archive):
        """Every depot path in one of the game's archives."""
        out = []
        for ar in self._game_archives(archive):
            for entry in ar.Files.Values:
                out.append(str(entry.FileName))
        return out

    def import_glb(self, glb_path, anims_in, anims_out, keep=True):
        """Import glb_path into a copy of anims_in, written to anims_out."""
        from System import Activator
        from System.IO import File, FileInfo, MemoryStream
        self._load_game()
        stream = MemoryStream()
        data = File.ReadAllBytes(anims_in)
        stream.Write(data, 0, data.Length)
        stream.Position = 0
        args_type = self._import.GetParameters()[2].ParameterType
        args = Activator.CreateInstance(args_type)
        args_type.GetProperty('Keep').SetValue(args, keep)
        if not self._import.Invoke(self.tools, [FileInfo(os.path.abspath(glb_path)), stream, args]):
            raise RuntimeError('WolvenKit refused the import of ' + glb_path)
        anims_out = os.path.abspath(anims_out)
        os.makedirs(os.path.dirname(anims_out), exist_ok=True)
        File.WriteAllBytes(anims_out, stream.ToArray())


def _files(folder):
    return [os.path.join(d, f) for d, _s, fs in os.walk(folder) for f in fs]


_shared = {}


def get(folder=None, game=DEFAULT_GAME, archives=()):
    """The WolvenKit for this run, loaded once."""
    key = (find(folder), game, tuple(archives))
    if key not in _shared:
        _shared[key] = WolvenKit(folder, game, archives)
    return _shared[key]


def depot_regex(depot):
    """A regex matching one depot path, for unbundle."""
    return '^' + re.escape(depot) + '$'
