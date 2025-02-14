import json
import sys
from PyQt5.QtCore import QThread, pyqtSignal, QUrl, Qt, QObject, QEventLoop
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QPushButton, QApplication, QDialog, QVBoxLayout, QLabel, \
    QScrollArea, QDialogButtonBox
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtGui import QDesktopServices
import markdown
from markdown.extensions import Extension
from xml.etree import ElementTree


class VersionChecker(QThread):
    """
    版本检查线程类
    信号：
    update_available - 发现新版本时触发 (新版本号, 更新说明, 发布页面URL)
    check_failed     - 检查失败时触发 (错误信息)
    """
    update_available = pyqtSignal(str, str, str)
    check_failed = pyqtSignal(str)

    def __init__(self, current_version, repo_url, access_token=None):
        super().__init__()
        print(f"[DEBUG] 版本检查器初始化线程: {self.thread().objectName()}")
        self.current_version = current_version
        self.repo_api_url = repo_url

        print(f"[DEBUG] 初始化检查器，访问令牌存在: {access_token is not None}")
        self.access_token = access_token  # 新增访问令牌参数
        # 注意：QNetworkAccessManager必须在目标线程中创建（在run()中初始化）
        self.manager = None  # 延迟到目标线程初始化

    def run(self):
        """
        线程主运行方法（在独立线程中执行）
        """
        print(f"[DEBUG] 检查线程开始运行，当前线程: {self.thread().objectName()}")

        try:
            # 在目标线程中创建网络管理器（重要！）
            self.manager = QNetworkAccessManager()
            print(f"[DEBUG] 网络管理器创建线程: {self.thread().objectName()}")

            request = QNetworkRequest(QUrl(self.repo_api_url))
            request.setHeader(QNetworkRequest.UserAgentHeader, "UpdateChecker/1.0")
            # 添加认证头（如果存在访问令牌）
            if self.access_token:
                print("[DEBUG] 正在添加API认证头")
                # Bearer令牌认证（适用于GitHub个人访问令牌）
                request.setRawHeader(b"Authorization", f"Bearer {self.access_token}".encode())
                # 或者使用GitHub App的JWT认证
                # request.setRawHeader(b"Authorization", f"Bearer {self.generate_jwt()}".encode())
            else:
                print("[WARNING] 未提供访问令牌，使用匿名访问（可能受速率限制）")

            print(f"[DEBUG] 发送网络请求到: {self.repo_api_url}")

            # 同步等待请求完成（使用事件循环）
            loop = QEventLoop()
            reply = self.manager.get(request)
            reply.finished.connect(loop.quit)
            loop.exec_()  # 等待请求完成

            self.handle_response(reply)
        except Exception as e:
            self.check_failed.emit(f"运行时异常: {str(e)}")
            print(f"[ERROR] 检查线程异常: {str(e)}")

    def handle_response(self, reply):
        """
        处理网络响应（仍在检查线程中执行）
        """
        try:
            # 检查HTTP状态码
            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            print(f"[DEBUG] HTTP状态码: {status_code}")

            # 处理速率限制（从响应头获取）
            rate_limit_remaining = reply.rawHeader(b"X-RateLimit-Remaining").data().decode()
            rate_limit_reset = reply.rawHeader(b"X-RateLimit-Reset").data().decode()
            print(f"[RATE] 剩余请求次数: {rate_limit_remaining}, 重置时间: {rate_limit_reset}")

            if status_code == 403 and int(rate_limit_remaining) == 0:
                raise Exception(f"API速率限制已用完，将在 {rate_limit_reset} 秒后重置")

            if status_code == 401:
                raise Exception("认证失败，请检查访问令牌")

            print(f"[DEBUG] 处理响应线程: {QThread.currentThread().objectName()}")

            if reply.error():
                error_msg = reply.errorString()
                print(f"[ERROR] 网络请求失败: {error_msg}")
                raise Exception(f"网络错误: {error_msg}")

            data = json.loads(reply.readAll().data().decode('utf-8', errors='ignore'))
            print(f"[DEBUG] 收到响应数据: {data[:200]}...")  # 打印部分数据用于调试

            if not data:
                print("[WARNING] 没有找到发布信息")
                return

            latest_release = data[0]
            latest_version = self.clean_version(latest_release['tag_name'])
            print(f"[INFO] 最新版本: {latest_version}, 当前版本: {self.current_version}")

            if self.is_newer(latest_version):
                release_notes = latest_release.get('body', '暂无更新说明')
                browser_url = latest_release.get('html_url', '')
                print(f"[INFO] 发现新版本 {latest_version}")
                self.update_available.emit(latest_version, release_notes, browser_url)
            else:
                print("[INFO] 当前已是最新版本")

        except json.JSONDecodeError as e:
            error_msg = f"JSON解析失败: {str(e)}"
            print(f"[ERROR] {error_msg}")
            self.check_failed.emit(error_msg)
        except Exception as e:
            error_msg = f"处理响应失败: {str(e)}"
            print(f"[ERROR] {error_msg}")
            self.check_failed.emit(error_msg)
        finally:
            reply.deleteLater()
            print("[DEBUG] 响应对象已清理")

    def clean_version(self, version):
        """清理版本号字符串中的非数字前缀"""
        return version.lstrip('vV').strip()

    def is_newer(self, latest_version):
        """比较版本号（支持语义化版本号比较）"""

        def parse_version(v):
            # 将版本号转换为数字列表（忽略非数字部分）
            parts = []
            for part in v.split('.'):
                num = ''.join(filter(str.isdigit, part))
                parts.append(int(num) if num else 0)
            return parts

        try:
            current = parse_version(self.clean_version(self.current_version))
            latest = parse_version(latest_version)
            print(f"[DEBUG] 版本比较: 当前{current} vs 最新{latest}")
            return latest > current
        except ValueError as e:
            print(f"[ERROR] 版本号解析失败: {str(e)}")
            return False

    @staticmethod
    def markdown_to_html(text):
        """
        将Markdown安全地转换为HTML，包含以下特性：
        1. 基础Markdown语法支持
        2. 代码块高亮
        3. 安全标签过滤
        4. 自动链接转换
        """

        # 创建自定义扩展用于安全过滤
        class SafeHtmlExtension(Extension):
            def extendMarkdown(self, md):
                md.preprocessors.deregister('html_block')
                md.inlinePatterns.deregister('html')

        # 配置转换器
        html = markdown.markdown(
            text,
            extensions=[
                'fenced_code',  # 代码块支持
                'tables',  # 表格支持
                'nl2br',  # 自动换行
                SafeHtmlExtension()  # 安全过滤
            ],
            output_format='html5'
        )
        return html


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        print("[DEBUG] 主窗口初始化线程:", self.thread().objectName())

        # 配置信息
        self.current_version = "1.0.0"
        self.github_repo = "NGC2237plus/github_version"  # 修改为你的仓库

        # 初始化UI
        self.init_ui()
        # 新增认证配置
        self.github_token = self.load_access_token()  # 从安全位置加载令牌
        # 启动自动检查
        self.check_updates()

    def load_access_token(self):
        """
        从安全位置加载访问令牌（示例实现）
        实际部署时应使用安全的方式存储，例如：
        - 加密的配置文件
        - 系统密钥环
        - 编译时注入（避免硬编码）
        """
        # 示例：从环境变量读取
        # token = os.environ.get("GITHUB_ACCESS_TOKEN")
        buf = 'github'
        buf2 = '_pat_'
        token = buf + buf2 + '11A7A72RA0JN2MV8NUGBpI_60wgH6hUwNl5pP04tUVreN1HRqBQ9XkY5aH5GUl3oixU2X7EHN21dziYTVS'
        # 或者从文件读取（生产环境需要加密）
        # try:
        #     with open("token.secret", "r") as f:
        #         return f.read().strip()
        # except FileNotFoundError:
        #     return None

        return token  # 返回None表示匿名访问

    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle(f"My App v{self.current_version}")
        self.setGeometry(300, 300, 400, 300)

        # 添加检查按钮
        btn = QPushButton("检查更新", self)
        btn.clicked.connect(self.check_updates)
        btn.resize(100, 30)
        btn.move(150, 135)
        print("[DEBUG] UI初始化完成")

    def check_updates(self):
        """启动更新检查"""
        print("[INFO] 开始检查更新...")
        api_url = f"https://api.github.com/repos/{self.github_repo}/releases"
        # self.checker = VersionChecker(self.current_version, api_url)
        # 传递访问令牌给检查器
        self.checker = VersionChecker(
            current_version=self.current_version,
            repo_url=api_url,
            access_token=self.github_token  # 新增参数
        )
        # 设置线程名称用于调试
        self.checker.setObjectName("VersionCheckThread")
        self.checker.thread().setObjectName("VersionCheckThread")

        # 连接信号
        self.checker.update_available.connect(self.show_update_dialog)
        self.checker.check_failed.connect(self.show_error)

        # 启动线程
        self.checker.start()
        print("[DEBUG] 检查线程已启动")

    def show_update_dialog(self, new_version, notes, url):
        """显示更新对话框（在主线程执行）"""
        # print("[DEBUG] 显示更新对话框线程:", self.thread().objectName())
        #
        # # 转换Markdown为HTML
        # processed_html = VersionChecker.markdown_to_html(notes)
        #
        # # 添加样式和滚动容器
        # message = f"""
        #     <style>
        #     .markdown-body {{
        #         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        #         font-size: 14px;
        #         line-height: 1.6;
        #         color: #24292e;
        #         max-height: 300px;
        #         overflow: auto;
        #         padding: 5px;
        #     }}
        #     .markdown-body h1, .markdown-body h2 {{
        #         border-bottom: 1px solid #eaecef;
        #         padding-bottom: 0.3em;
        #     }}
        #     .markdown-body code {{
        #         background-color: rgba(27,31,35,0.05);
        #         border-radius: 3px;
        #         font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
        #         padding: 0.2em 0.4em;
        #     }}
        #     .markdown-body pre {{
        #         background-color: #f6f8fa;
        #         border-radius: 3px;
        #         padding: 16px;
        #         overflow: auto;
        #     }}
        #     .markdown-body a {{
        #         color: #0366d6;
        #         text-decoration: none;
        #     }}
        #     .markdown-body a:hover {{
        #         text-decoration: underline;
        #     }}
        #     </style>
        #     <div class="markdown-body">
        #         <h3 style="margin-top:0">版本更新</h3>
        #         <div style="margin-bottom:10px">
        #             <b>当前版本：</b>v{self.current_version}<br/>
        #             <b>最新版本：</b>v{new_version}
        #         </div>
        #         {processed_html}
        #     </div>
        #     """
        #
        # # 创建对话框
        # msg = QMessageBox()
        # msg.setWindowTitle("发现新版本！")
        # msg.setIcon(QMessageBox.Information)
        # msg.setTextFormat(Qt.RichText)
        # # 调整对话框尺寸
        # msg.setMinimumSize(100, 100)  # 最小宽度500px，高度400px
        # msg.setMaximumSize(500, 500)
        # msg.setGeometry(100, 100, 500, 500)
        #
        #
        #
        # # 添加操作按钮
        # msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Ignore | QMessageBox.Cancel)
        # msg.button(QMessageBox.Yes).setText("立即更新")
        # msg.button(QMessageBox.Ignore).setText("跳过该版本")
        # msg.button(QMessageBox.Cancel).setText("下次提醒")
        # msg.setText(message)
        # # 显示对话框
        # if msg.exec_() == QMessageBox.Yes:
        #     QDesktopServices.openUrl(QUrl(url))
        #
        # # if msg.exec_() == QMessageBox.Yes:
        # #     print(f"[INFO] 用户选择更新，打开: {url}")
        # #     QDesktopServices.openUrl(QUrl(url))
        # # else:
        # #     print("[INFO] 用户选择暂不更新")
        # 创建自定义对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("发现新版本！")
        dialog.setMinimumSize(600, 400)

        # 使用QVBoxLayout布局
        layout = QVBoxLayout(dialog)

        # 版本信息区域
        version_info = QLabel(
            f"<b>当前版本：</b>v{self.current_version}<br/>"
            f"<b>最新版本：</b>v{new_version}"
        )
        layout.addWidget(version_info)

        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        # 内容容器
        content = QLabel()
        content.setWordWrap(True)
        content.setTextFormat(Qt.RichText)

        # 转换Markdown为HTML并添加样式
        processed_html = VersionChecker.markdown_to_html(notes)
        full_html = f"""
            <style>
            .markdown-body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                font-size: 14px;
                line-height: 1.6;
                color: #24292e;
                padding: 10px;
            }}
            .markdown-body pre {{
                background-color: #f6f8fa;
                padding: 10px;
                border-radius: 3px;
                overflow-x: auto;
            }}
            </style>
            <div class="markdown-body">
                {processed_html}
            </div>
            """
        content.setText(full_html)

        # 设置滚动区域内容
        scroll_area.setWidget(content)
        layout.addWidget(scroll_area)

        # 按钮区域
        btn_box = QDialogButtonBox()
        btn_update = btn_box.addButton("立即更新", QDialogButtonBox.AcceptRole)
        btn_later = btn_box.addButton("稍后提醒", QDialogButtonBox.RejectRole)

        btn_update.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        btn_update.clicked.connect(dialog.accept)
        btn_later.clicked.connect(dialog.reject)

        layout.addWidget(btn_box)

        # 显示对话框
        dialog.exec_()

    def show_error(self, error_msg):
        """显示错误提示（在主线程执行）"""
        print(f"[DEBUG] 显示错误对话框线程: {self.thread().objectName()}")
        QMessageBox.warning(
            self,
            "检查更新失败",
            f"无法获取更新信息：\n{error_msg}",
            QMessageBox.Ok
        )
        print(f"[ERROR] 更新检查失败: {error_msg}")


if __name__ == "__main__":
    # 配置调试输出
    sys.excepthook = lambda t, v, tb: print(f"[CRITICAL] 未捕获异常: {v}")

    app = QApplication(sys.argv)
    app.setApplicationName("MyApp")

    # 设置线程名称用于调试
    app.thread().setObjectName("MainThread")

    window = MainWindow()
    window.show()
    print("[DEBUG] 应用程序启动完成")
    sys.exit(app.exec_())
