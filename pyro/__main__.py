import argparse
import logging
import os
import sys

from pyro.BuildFacade import BuildFacade
from pyro.PapyrusProject import PapyrusProject
from pyro.PathHelper import PathHelper
from pyro.ProjectOptions import ProjectOptions
from pyro.PyroArgumentParser import PyroArgumentParser
from pyro.PyroRawDescriptionHelpFormatter import PyroRawTextHelpFormatter
from pyro.TimeElapsed import TimeElapsed


class Application:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname).4s] %(message)s')
    log = logging.getLogger('pyro')

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self._validate_args()

    def _validate_args(self) -> None:
        if self.args.show_help:
            sys.exit(print_help())

        input_path: str = self.args.input_path

        if not input_path:
            Application.log.error('required argument missing: -i INPUT.ppj')
            sys.exit(print_help())

        if not input_path.casefold().endswith('.ppj'):
            Application.log.error('Single script compilation is no longer supported. Use a PPJ file.')
            sys.exit(print_help())

        if input_path.casefold().startswith('file:'):
            full_path: str = PathHelper.url2pathname(input_path)
            input_path = os.path.normpath(full_path)

        if not os.path.isabs(input_path):
            Application.log.warning('Using working directory: "%s"' % os.getcwd())
            input_path = os.path.join(os.getcwd(), input_path)
            Application.log.warning('Using input path: "%s"' % input_path)

        self.args.input_path = input_path

        if not os.path.isfile(self.args.input_path):
            Application.log.error('Cannot load PPJ at given path because file does not exist: "%s"' % self.args.input_path)
            sys.exit(print_help())

    @staticmethod
    def _validate_project(ppj: PapyrusProject) -> None:
        if not ppj.options.game_path:
            Application.log.error('Cannot determine game type from arguments or Papyrus Project')
            sys.exit(print_help())

        if not ppj.has_imports_node:
            Application.log.error('Cannot proceed without imports defined in project')
            sys.exit(print_help())

        if not ppj.has_scripts_node:
            Application.log.error('Cannot proceed without Scripts defined in project')
            sys.exit(print_help())

        if ppj.options.package and not ppj.has_packages_node:
            Application.log.error('Cannot proceed with Package enabled without Packages defined in project')
            sys.exit(print_help())

        if ppj.options.zip and not ppj.has_zip_file_node:
            Application.log.error('Cannot proceed with Zip enabled without ZipFile defined in project')
            sys.exit(print_help())

    def run(self) -> int:
        options = ProjectOptions(self.args.__dict__)
        ppj = PapyrusProject(options)

        self._validate_project(ppj)

        Application.log.info('Imports found:')
        for path in ppj.import_paths:
            Application.log.info('+ "%s"' % path)

        Application.log.info('Scripts found:')
        for path in ppj.psc_paths:
            Application.log.info('+ "%s"' % path)

        time_elapsed = TimeElapsed()

        build = BuildFacade(ppj)

        # bsarch path is not set until BuildFacade initializes
        if ppj.options.package and not os.path.isfile(ppj.options.bsarch_path):
            Application.log.error('Cannot proceed with Package enabled without valid BSArch path')
            sys.exit(print_help())

        success_count, failed_count = build.try_compile(time_elapsed)

        if ppj.options.anonymize:
            if failed_count == 0 or ppj.options.ignore_errors:
                build.try_anonymize()
            else:
                Application.log.warning('Cannot anonymize scripts because %s scripts failed to compile' % failed_count)
        else:
            Application.log.warning('Cannot anonymize scripts because Anonymize is disabled in project')

        if ppj.options.package:
            if failed_count == 0 or ppj.options.ignore_errors:
                build.try_pack()
            else:
                Application.log.warning('Cannot create Packages because %s scripts failed to compile' % failed_count)
        else:
            Application.log.warning('Cannot create Packages because Package is disabled in project')

        if ppj.options.zip:
            if failed_count == 0 or ppj.options.ignore_errors:
                build.try_zip()
            else:
                Application.log.warning('Cannot create ZipFile because %s scripts failed to compile' % failed_count)
        else:
            Application.log.warning('Cannot create ZipFile because Zip is disabled in project')

        if success_count > 0:
            raw_time = time_elapsed.value()
            avg_time = time_elapsed.average(success_count)
            s_raw_time, s_avg_time = ('{0:.3f}s'.format(t) for t in (raw_time, avg_time))

            psc_count = len(ppj.psc_paths)

            Application.log.info('Compilation time: %s (%s/script) - %s succeeded, %s failed (%s scripts)'
                                 % (s_raw_time, s_avg_time, success_count, failed_count, psc_count))
        else:
            Application.log.info('No scripts were compiled.')

        Application.log.info('DONE!')

        return 0


if __name__ == '__main__':
    _parser = PyroArgumentParser(add_help=False,
                                 formatter_class=PyroRawTextHelpFormatter,
                                 description=os.linesep.join([
                                     '-' * 80,
                                     ''.join([c.center(3) for c in 'PYRO']).center(80),
                                     '-' * 53 + ' github.com/fireundubh/pyro'
                                 ]))

    _required_arguments = _parser.add_argument_group('required arguments')
    _required_arguments.add_argument('-i', '--input-path',
                                     action='store', type=str,
                                     help='relative or absolute path to ppj file\n'
                                          '(if relative, must be relative to current working directory)')

    _build_arguments = _parser.add_argument_group('build arguments')
    _build_arguments.add_argument('--ignore-errors',
                                  action='store_true', default=False,
                                  help='ignore compiler errors during build')
    _build_arguments.add_argument('--no-incremental-build',
                                  action='store_true', default=False,
                                  help='do not build incrementally')
    _build_arguments.add_argument('--no-parallel',
                                  action='store_true', default=False,
                                  help='do not parallelize compilation')
    _build_arguments.add_argument('--worker-limit',
                                  action='store', type=int,
                                  help='max workers for parallel compilation\n'
                                       '(usually set automatically to processor count)')

    _compiler_arguments = _parser.add_argument_group('compiler arguments')
    _compiler_arguments.add_argument('--compiler-path',
                                     action='store', type=str,
                                     help='relative or absolute path to PapyrusCompiler.exe\n'
                                          '(if relative, must be relative to current working directory)')
    _compiler_arguments.add_argument('--flags-path',
                                     action='store', type=str,
                                     help='relative or absolute path to Papyrus Flags file\n'
                                          '(if relative, must be relative to project)')
    _compiler_arguments.add_argument('--output-path',
                                     action='store', type=str,
                                     help='relative or absolute path to output folder\n'
                                          '(if relative, must be relative to project)')

    _game_arguments = _parser.add_argument_group('game arguments')
    _game_arguments.add_argument('-g', '--game-type',
                                 action='store', type=str,
                                 choices={'fo4', 'tesv', 'sse'},
                                 help='set game type (choices: fo4, tesv, sse)')

    _game_path_arguments = _game_arguments.add_mutually_exclusive_group()
    _game_path_arguments.add_argument('--game-path',
                                      action='store', type=str,
                                      help='relative or absolute path to game install directory\n'
                                           '(if relative, must be relative to current working directory)')
    if sys.platform == 'win32':
        _game_path_arguments.add_argument('--registry-path',
                                          action='store', type=str,
                                          help='path to Installed Path key in Windows Registry')

    _bsarch_arguments = _parser.add_argument_group('bsarch arguments')
    _bsarch_arguments.add_argument('--bsarch-path',
                                   action='store', type=str,
                                   help='relative or absolute path to bsarch.exe\n'
                                        '(if relative, must be relative to current working directory)')
    _bsarch_arguments.add_argument('--package-path',
                                   action='store', type=str,
                                   help='relative or absolute path to bsa/ba2 output folder\n'
                                        '(if relative, must be relative to project)')
    _bsarch_arguments.add_argument('--temp-path',
                                   action='store', type=str,
                                   help='relative or absolute path to temp folder\n'
                                        '(if relative, must be relative to current working directory)')

    _zip_arguments = _parser.add_argument_group('zip arguments')
    _zip_arguments.add_argument('--zip-compression',
                                action='store', type=str,
                                choices={'store', 'deflate'},
                                help='set compression method (choices: store, deflate)')
    _zip_arguments.add_argument('--zip-output-path',
                                action='store', type=str,
                                help='relative or absolute path to zip output folder\n'
                                     '(if relative, must be relative to project)')

    _program_arguments = _parser.add_argument_group('program arguments')
    _program_arguments.add_argument('--log-path',
                                    action='store', type=str,
                                    help='relative or absolute path to log folder\n'
                                         '(if relative, must be relative to current working directory)')
    _program_arguments.add_argument('--help', dest='show_help',
                                    action='store_true', default=False,
                                    help='show help and exit')


    def print_help() -> int:
        _parser.print_help()
        return 1


    Application(_parser.parse_args()).run()
