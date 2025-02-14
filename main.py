"""
@FileName：   main.py
@Description：描述
@Author：     NGC2237
@Version:     1.0
@Time：       2025/2/14
@Software：   PyCharm
"""
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QPushButton, QApplication
from PyQt5.QtCore import QCoreApplication, Qt, QUrl
from version import VersionChecker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 配置信息v
        self.current_version = "1.0.0"  # 确保与GitHub tag一致
        self.github_repo = "NGC2237plus/github_version"

        # 初始化UI
        self.init_ui()

        # 开始检查更新
        self.check_updates()

    def init_ui(self):
        self.setWindowTitle(f"My App v{self.current_version}")
        self.setGeometry(300, 300, 400, 300)

        # 添加手动检查按钮
        btn = QPushButton("检查更新", self)
        btn.clicked.connect(self.check_updates)
        btn.resize(100, 30)
        btn.move(150, 135)

    def check_updates(self):
        api_url = f"https://api.github.com/repos/{self.github_repo}/releases"
        self.checker = VersionChecker(self.current_version, api_url)
        self.checker.update_available.connect(self.show_update_dialog)
        self.checker.check_failed.connect(self.show_error)
        self.checker.start()

    def show_update_dialog(self, new_version, notes, url):
        msg = QMessageBox()
        msg.setWindowTitle("发现新版本！")
        msg.setIcon(QMessageBox.Information)
        msg.setTextFormat(Qt.RichText)

        message = f"""
        <b>当前版本：v{self.current_version}</b><br/>
        <b>最新版本：v{new_version}</b><br/><br/>
        <div style='max-height:200px; overflow:auto;'>
        {notes.replace('   ', '<br/>')}
        </div>
        """

        msg.setText(message)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.button(QMessageBox.Yes).setText("立即更新")
        msg.button(QMessageBox.No).setText("稍后提醒")
        msg.setDefaultButton(QMessageBox.Yes)

        if msg.exec_() == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(url))

    def show_error(self, error_msg):
        QMessageBox.warning(
            self,
            "检查更新失败",
            f"无法获取更新信息：\n{error_msg}",
            QMessageBox.Ok
        )


if __name__ == "__main__":
    import sys

    app = QCoreApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())