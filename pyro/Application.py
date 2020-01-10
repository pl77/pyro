import argparse
import logging
import os
import sys

from pyro.BuildFacade import BuildFacade
from pyro.PapyrusProject import PapyrusProject
from pyro.PathHelper import PathHelper
from pyro.PexReader import PexReader
from pyro.ProjectOptions import ProjectOptions
from pyro.TimeElapsed import TimeElapsed


class Application:
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format='%(asctime)s [%(levelname).4s] %(message)s')
    log = logging.getLogger('pyro')

    args: argparse.Namespace = None

    def __init__(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser

        self.args = self.parser.parse_args()

        if self.args.show_help:
            self._print_help_and_exit()

        self.args.input_path = self._try_fix_input_path(self.args.input_path)

        if not os.path.isfile(self.args.input_path):
            Application.log.error(f'Cannot load PPJ at given path because file does not exist: "{self.args.input_path}"')
            self._print_help_and_exit()

    def _print_help_and_exit(self) -> None:
        self.parser.print_help()
        sys.exit(1)

    def _try_fix_input_path(self, input_path: str) -> str:
        if not input_path:
            Application.log.error('required argument missing: -i INPUT.ppj')
            self._print_help_and_exit()

        if input_path.casefold().startswith('file:'):
            full_path = PathHelper.url2pathname(input_path)
            input_path = os.path.normpath(full_path)

        if not os.path.isabs(input_path):
            cwd = os.getcwd()
            Application.log.warning(f'Using working directory: "{cwd}"')

            input_path = os.path.join(cwd, input_path)

        Application.log.warning(f'Using input path: "{input_path}"')

        return input_path

    def _validate_project(self, ppj: PapyrusProject) -> None:
        if not ppj.options.game_path:
            Application.log.error('Cannot determine game type from arguments or Papyrus Project')
            self._print_help_and_exit()

        if not ppj.has_imports_node:
            Application.log.error('Cannot proceed without imports defined in project')
            self._print_help_and_exit()

        if not ppj.has_scripts_node and not ppj.has_folders_node:
            Application.log.error('Cannot proceed without Scripts or Folders defined in project')
            self._print_help_and_exit()

        if ppj.options.package and not ppj.has_packages_node:
            Application.log.error('Cannot proceed with Package enabled without Packages defined in project')
            self._print_help_and_exit()

        if ppj.options.zip and not ppj.has_zip_file_node:
            Application.log.error('Cannot proceed with Zip enabled without ZipFile defined in project')
            self._print_help_and_exit()

    def run(self) -> int:
        _, extension = os.path.splitext(os.path.basename(self.args.input_path).casefold())

        if extension == '.pex':
            header = PexReader.dump(self.args.input_path)
            Application.log.info(f'Dumping: "{self.args.input_path}"\n{header}')
            sys.exit(0)
        elif extension not in ('.ppj', '.pyroproject'):
            Application.log.error('Cannot proceed without PPJ file path')
            self._print_help_and_exit()

        options = ProjectOptions(self.args.__dict__)
        ppj = PapyrusProject(options)

        self._validate_project(ppj)

        Application.log.info('Imports found:')
        for path in ppj.import_paths:
            Application.log.info(f'+ "{path}"')

        Application.log.info('Scripts found:')
        for path in ppj.psc_paths:
            Application.log.info(f'+ "{path}"')

        time_elapsed = TimeElapsed()

        build = BuildFacade(ppj)

        # bsarch path is not set until BuildFacade initializes
        if ppj.options.package and not os.path.isfile(ppj.options.bsarch_path):
            Application.log.error('Cannot proceed with Package enabled without valid BSArch path')
            self._print_help_and_exit()

        success_count, failed_count = build.try_compile(time_elapsed)

        if ppj.options.anonymize:
            if failed_count == 0 or ppj.options.ignore_errors:
                build.try_anonymize()
            else:
                Application.log.warning(f'Cannot anonymize scripts because {failed_count} scripts failed to compile')
        else:
            Application.log.warning('Cannot anonymize scripts because Anonymize is disabled in project')

        if ppj.options.package:
            if failed_count == 0 or ppj.options.ignore_errors:
                build.try_pack()
            else:
                Application.log.warning(f'Cannot create Packages because {failed_count} scripts failed to compile')
        else:
            Application.log.warning('Cannot create Packages because Package is disabled in project')

        if ppj.options.zip:
            if failed_count == 0 or ppj.options.ignore_errors:
                build.try_zip()
            else:
                Application.log.warning(f'Cannot create ZipFile because {failed_count} scripts failed to compile')
        else:
            Application.log.warning('Cannot create ZipFile because Zip is disabled in project')

        if success_count > 0:
            raw_time = time_elapsed.value()
            avg_time = time_elapsed.average(success_count)
            s_raw_time, s_avg_time = ('{0:.3f}s'.format(t) for t in (raw_time, avg_time))

            psc_count = len(ppj.psc_paths)

            Application.log.info(f'Compilation time: {s_raw_time} ({s_avg_time}/script) - {success_count} succeeded, {failed_count} failed ({psc_count} scripts)')
        else:
            Application.log.info('No scripts were compiled.')

        Application.log.info('DONE!')

        return 0
