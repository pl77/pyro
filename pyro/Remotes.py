import json
import os
from typing import Generator
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pyro.Comparators import endswith
from pyro.ProjectOptions import ProjectOptions


class RemoteBase:
    access_token: str = ''

    def __init__(self, options: ProjectOptions) -> None:
        self.options = options
        self.access_token = options.access_token

    @staticmethod
    def create_local_path(url: str) -> str:
        """
        Creates relative local path from URL
        """
        parsed_url = urlparse(url)

        url_path_parts = parsed_url.path.split('/')
        url_path_parts.pop(0)  # pop empty space

        if parsed_url.netloc == 'api.github.com':
            url_path_parts.pop(3)  # pop 'contents'
            url_path_parts.pop(0)  # pop 'repos'
        elif parsed_url.netloc == 'github.com':
            url_path_parts.pop(3)  # pop 'master' (or any other branch)
            url_path_parts.pop(2)  # pop 'tree'
        elif parsed_url.netloc == 'api.bitbucket.org':
            url_path_parts.pop(5)  # pop branch
            url_path_parts.pop(4)  # pop 'src'
            url_path_parts.pop(1)  # pop 'repositories'
            url_path_parts.pop(0)  # pop '2.0'
        elif parsed_url.netloc == 'bitbucket.org':
            url_path_parts.pop(3)  # pop branch
            url_path_parts.pop(2)  # pop 'src'
        else:
            raise NotImplementedError

        url_path = os.sep.join(url_path_parts)

        return url_path

    @staticmethod
    def extract_request_args(url: str) -> tuple:
        """
        Extracts (owner, repo, request_url) from URL
        """
        parsed_url = urlparse(url)

        url_path_parts = parsed_url.path.split('/')
        url_path_parts.pop(0)  # pop empty space

        if parsed_url.netloc == 'api.github.com':
            url_path_parts.pop(0)  # pop 'repos'
            request_url = url
        elif parsed_url.netloc == 'github.com':
            branch = url_path_parts.pop(3)  # pop 'master' (or any other branch)
            url_path_parts.pop(2)  # pop 'tree'
            url_path_parts.insert(2, 'contents')
            url_path = '/'.join(url_path_parts)
            request_url = f'https://api.github.com/repos/{url_path}?ref={branch}'
        elif parsed_url.netloc == 'api.bitbucket.org':
            request_url = url
        elif parsed_url.netloc == 'bitbucket.org':
            request_url = f'https://api.bitbucket.org/2.0/repositories{parsed_url.path}{parsed_url.query}'
        else:
            raise NotImplementedError

        owner, repo = url_path_parts[0], url_path_parts[1]

        return owner, repo, request_url

    @staticmethod
    def validate_url(url: str) -> bool:
        """
        Tests whether URL has scheme, netloc, and path
        """
        try:
            result = urlparse(url)
        except HTTPError:
            return False
        else:
            return all([result.scheme, result.netloc, result.path])

    def fetch_contents(self, url: str, output_path: str) -> Generator:
        """
        Downloads files from URL to output path
        """
        pass


class GenericRemote(RemoteBase):
    def fetch_contents(self, url: str, output_path: str) -> Generator:
        """
        Downloads files from URL to output path
        """
        parsed_url = urlparse(url)

        if parsed_url.netloc.endswith('github.com'):
            if not self.options.access_token:
                raise PermissionError('Cannot download from GitHub remote without access token')
            github = GitHubRemote(self.options)
            yield from github.fetch_contents(url, output_path)
        elif parsed_url.netloc.endswith('bitbucket.org'):
            bitbucket = BitbucketRemote(self.options)
            yield from bitbucket.fetch_contents(url, output_path)
        else:
            raise NotImplementedError


class BitbucketRemote(RemoteBase):
    def _fetch_payloads(self, request_url: str) -> Generator:
        """
        Recursively generates payloads from paginated responses
        """
        request = Request(request_url)

        response = urlopen(request, timeout=30)

        if response.status != 200:
            yield 'Failed to load URL (%s): "%s"' % (response.status, request_url)
            return

        payload: dict = json.loads(response.read().decode('utf-8'))

        yield payload

        if 'next' in payload:
            yield from self._fetch_payloads(payload['next'])

    def fetch_contents(self, url: str, output_path: str) -> Generator:
        """
        Downloads files from URL to output path
        """
        owner, repo, request_url = self.extract_request_args(url)

        yield f'Downloading scripts from "{request_url}"... Please wait.'

        script_count: int = 0

        for payload in self._fetch_payloads(request_url):
            for payload_object in payload['values']:
                payload_object_type = payload_object['type']

                target_path = os.path.normpath(os.path.join(output_path, owner, repo, payload_object['path']))

                download_url = payload_object['links']['self']['href']

                if payload_object_type == 'commit_file':
                    # we only care about scripts
                    if not endswith(download_url, '.psc', ignorecase=True):
                        continue

                    file_response = urlopen(download_url, timeout=30)

                    if file_response.status != 200:
                        yield f'Failed to download ({file_response.status}): "{download_url}"'
                        continue

                    os.makedirs(os.path.dirname(target_path), exist_ok=True)

                    with open(target_path, mode='w+b') as f:
                        f.write(file_response.read())

                    script_count += 1

                elif payload_object_type == 'commit_directory':
                    yield from self.fetch_contents(download_url, output_path)

        if script_count > 0:
            yield f'Downloaded {script_count} scripts from "{request_url}"'


class GitHubRemote(RemoteBase):
    def fetch_contents(self, url: str, output_path: str) -> Generator:
        """
        Downloads files from URL to output path
        """
        owner, repo, request_url = self.extract_request_args(url)

        request = Request(request_url)
        request.add_header('Authorization', f'token {self.access_token}')

        response = urlopen(request, timeout=30)

        if response.status != 200:
            yield 'Failed to load URL (%s): "%s"' % (response.status, request_url)
            return

        payload_objects: list = json.loads(response.read().decode('utf-8'))

        yield f'Downloading scripts from "{request_url}"... Please wait.'

        script_count: int = 0

        for payload_object in payload_objects:
            target_path = os.path.normpath(os.path.join(output_path, owner, repo, payload_object['path']))

            download_url = payload_object['download_url']

            # handle folders
            if not download_url:
                yield from self.fetch_contents(payload_object['url'], output_path)
                continue

            # we only care about scripts
            if not endswith(download_url, '.psc', ignorecase=True):
                continue

            file_response = urlopen(download_url, timeout=30)
            if file_response.status != 200:
                yield f'Failed to download ({file_response.status}): "{payload_object["download_url"]}"'
                continue

            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            with open(target_path, mode='w+b') as f:
                f.write(file_response.read())

            script_count += 1

        if script_count > 0:
            yield f'Downloaded {script_count} scripts from "{request_url}"'
