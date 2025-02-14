"""
@FileName：   version.py
@Description：描述
@Author：     NGC2237
@Version:     1.0
@Time：       2025/2/14
@Software：   PyCharm
"""
import json
from PyQt5.QtCore import QThread, pyqtSignal, QUrl, Qt
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest


class VersionChecker(QThread):
    update_available = pyqtSignal(str, str, str)  # (new_version, release_notes, url)
    check_failed = pyqtSignal(str)

    def __init__(self, current_version, repo_url):
        super().__init__()
        self.current_version = current_version
        self.repo_api_url = repo_url
        self.manager = QNetworkAccessManager()

    def run(self):
        request = QNetworkRequest(QUrl(self.repo_api_url))
        request.setHeader(QNetworkRequest.UserAgentHeader, "UpdateChecker/1.0")

        reply = self.manager.get(request)
        reply.finished.connect(
            lambda: self.handle_response(reply)
        )

    def handle_response(self, reply):
        try:
            if reply.error():
                raise Exception(reply.errorString())

            data = json.loads(reply.readAll().data().decode())
            if not data:
                return

            latest_release = data[0]
            latest_version = self.clean_version(latest_release['tag_name'])

            if self.is_newer(latest_version):
                release_notes = latest_release.get('body', '暂无更新说明')
                browser_url = latest_release.get('html_url', '')
                self.update_available.emit(latest_version, release_notes, browser_url)

        except Exception as e:
            self.check_failed.emit(str(e))
        finally:
            reply.deleteLater()

    def clean_version(self, version):
        return version.lstrip('vV').strip()

    def is_newer(self, latest_version):
        def parse(v):
            return [int(num) for num in v.split('.') if num.isdigit()]

        try:
            current = parse(self.clean_version(self.current_version))
            latest = parse(latest_version)
            return latest > current
        except:
            return False