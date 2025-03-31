# encoding:utf-8
import json
import os

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from lib.gewechat import GewechatClient
from plugins import Plugin, EventContext, EventAction, Event
from plugins.PKTracker.admin_manager import AdminManager
from plugins.PKTracker.checkin_manager import CheckinManager
from plugins.PKTracker.database import DatabaseManager
from plugins.PKTracker.ranking_manager import RankingManager
from plugins.PKTracker.scheduler import TaskScheduler
from plugins.PKTracker.task_manager import TaskManager
from plugins.PKTracker.user_manager import UserManager


@plugins.register(
    name="PKTracker",
    desire_priority=10,
    hidden=False,
    enabled=True,
    desc="微信群打卡PK插件",
    version="1.0.0",
    author="Miragic",
)
class PKTracker(Plugin):
    _instance = None
    _scheduler_initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            super().__init__()
            try:
                self.config = super().load_config()
                if not self.config:
                    self.config = self._load_config_template()

                # 初始化数据库
                db_name = self.config.get("db_path", "pkTracker.db")
                self.db_path = os.path.join(os.path.dirname(__file__), db_name)
                self.db_manager = DatabaseManager(self.db_path)

                # 初始化客户端
                self._init_client()

                # 初始化各个管理器
                self.task_manager = TaskManager(self.db_path)
                self.checkin_manager = CheckinManager(self.db_path)
                self.user_manager = UserManager(self.client, self.app_id)
                self.admin_manager = AdminManager(self.db_path, self.config, self.user_manager)
                self.ranking_manager = RankingManager(self.db_path, self.user_manager)

                # 只在第一次初始化时创建和启动调度器
                if not PKTracker._scheduler_initialized:
                    self.scheduler = TaskScheduler(self.db_path, self)
                    self.scheduler.start_scheduler()
                    PKTracker._scheduler_initialized = True

                # 注册事件处理器
                self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
                self._initialized = True

                logger.info("[PKTracker] 初始化成功")
            except Exception as e:
                logger.error(f"[PKTracker] 初始化异常：{e}")
                raise Exception(f"[PKTracker] init failed: {str(e)}")

    def __del__(self):
        """析构函数，确保调度器正确关闭"""
        try:
            if PKTracker._scheduler_initialized and hasattr(self, 'scheduler'):
                self.scheduler.stop_scheduler()
                PKTracker._scheduler_initialized = False
                logger.info("[PKTracker] 调度器已停止")
        except Exception as e:
            logger.error(f"[PKTracker] 停止调度器异常: {str(e)}")

    def _init_client(self):
        """初始化微信客户端"""
        self.gewechat_config = self._load_root_config()
        if self.gewechat_config:
            self.app_id = self.gewechat_config.get("gewechat_app_id")
            self.base_url = self.gewechat_config.get("gewechat_base_url")
            self.token = self.gewechat_config.get("gewechat_token")
            self.client = GewechatClient(self.base_url, self.token)
        else:
            logger.error("[PKTracker] 无法加载根目录的 config.json 文件，GewechatClient 初始化失败")
            self.client = None

    def _load_config_template(self):
        """加载配置模板"""
        try:
            plugin_config_path = os.path.join(self.path, "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.exception(e)
        return {}

    def _load_config(self):
        """加载插件配置"""
        try:
            plugin_config_path = os.path.join(os.path.dirname(__file__), "config.json")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.exception(e)
        return {}

    def _load_root_config(self):
        """加载根目录的 config.json 文件"""
        try:
            root_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json")
            if os.path.exists(root_config_path):
                with open(root_config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                logger.error(f"[PKTracker] 根目录的 config.json 文件不存在: {root_config_path}")
                return None
        except Exception as e:
            logger.error(f"[PKTracker] 加载根目录的 config.json 文件失败: {e}")
            return None

    def is_group_chat(self, chat_id: str) -> bool:
        """判断是否是群聊消息"""
        return chat_id.endswith('@chatroom')

    def on_handle_context(self, e_context: EventContext):
        """处理消息事件"""
        context = e_context["context"]
        if context.type != ContextType.TEXT:
            return

        content = context.content
        if not content.startswith("PKTracker"):
            return
        receiver_value = context.kwargs.get("receiver")

        try:
            # 检查是否为群聊消息
            if not self.is_group_chat(receiver_value):
                reply = Reply(ReplyType.TEXT, "❌ 该功能仅支持在群聊中使用")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return

            group_id = receiver_value
            session_id = context.kwargs.get("session_id", "")
            user_id = session_id.split('@@')[0]

            # 解析命令
            parts = content.split()
            if len(parts) < 2:
                reply = Reply(ReplyType.TEXT, "格式错误,请输入正确的指令")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return

            command = parts[1]
            reply_text = self.handle_command(command, parts, user_id, group_id)

            reply = Reply(ReplyType.TEXT, reply_text)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS

        except Exception as e:
            logger.exception(f"[PKTracker] 处理消息异常: {str(e)}")
            reply = Reply(ReplyType.ERROR, "处理命令时出错,请稍后再试")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS

    def handle_command(self, command, parts, user_id, group_id):
        """处理各种命令"""
        # 处理打卡命令
        if command.startswith("[") and command.endswith("]"):
            task_name = command[1:-1]
            if len(parts) < 3:
                return "请输入打卡内容"
            content = " ".join(parts[2:])
            return self.checkin_manager.handle_checkin(user_id, group_id, task_name, content)

        # 处理管理员命令
        elif command == "设置频率":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以设置频率"
            elif len(parts) != 4:
                return "格式错误,请使用: PKTracker 设置频率 [任务名称] [日/周/月]"
            task_name = parts[2][1:-1]
            frequency = parts[3][1:-1]
            result = self.task_manager.set_frequency(group_id, task_name, frequency)
            if result.startswith("✅"):  # 如果设置成功
                return result + "\n\n" + self.task_manager.get_task_list(group_id)
            return result

        # 处理查询命令
        elif command == "积分榜":
            return self.ranking_manager.get_ranking(group_id, parts[2] if len(parts) > 2 else None)

        # 处理任务列表命令
        elif command == "任务列表":
            return self.task_manager.get_task_list(group_id)

        # 处理查看管理员命令
        elif command == "查看管理员":
            return self.admin_manager.get_admin_list(group_id)

        # 处理帮助命令
        elif command == "help":
            return self.get_help_text()

        # 处理添加管理员命令
        elif command == "添加管理员":
            if len(parts) != 3 or not (parts[2].startswith('[') and parts[2].endswith(']')):
                return "格式错误,请使用: PKTracker 添加管理员 [用户名]"
            user_name = parts[2][1:-1]
            # 获取用户ID
            u_id = self.user_manager._get_user_id_by_nickname(user_name)
            if not u_id:
                return f"❌ 未找到用户 [{user_name}]"
            return self.admin_manager.add_admin(group_id, u_id, user_id, user_name)

        # 处理取消管理员命令
        elif command == "取消管理员":
            if len(parts) != 3 or not (parts[2].startswith('[') and parts[2].endswith(']')):
                return "格式错误,请使用: PKTracker 取消管理员 [用户名]"
            user_name = parts[2][1:-1]
            # 获取用户ID
            u_id = self.user_manager._get_user_id_by_nickname(user_name)
            if not u_id:
                return f"❌ 未找到用户 [{user_name}]"
            return self.admin_manager.remove_admin(group_id, u_id, user_id, user_name)

        # 处理创建打卡任务命令
        elif command == "创建任务":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员或者超级管理员可以创建任务"
            elif len(parts) < 3 or not (parts[2].startswith('[') and parts[2].endswith(']')):
                return "格式错误,请使用: PKTracker 创建任务 [任务名称]"
            task_name = parts[2][1:-1]
            return self.task_manager.create_task(group_id, task_name)

        elif command == "设置次数":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以设置打卡次数"
            elif len(parts) != 4 or not (parts[2].startswith('[') and parts[2].endswith(']')):
                return "格式错误,请使用: PKTracker 设置次数 [任务名称] [次数]"
            try:
                task_name = parts[2][1:-1]
                max_checkins = int(parts[3][1:-1])
                # 直接返回 task_manager 的结果，不需要再次获取任务列表
                return self.task_manager.set_max_checkins(group_id, task_name, max_checkins)
            except ValueError:
                return "❌ 次数必须是整数且大于0"

        elif command == "任务详情":
            if len(parts) != 3 or not (parts[2].startswith('[') and parts[2].endswith(']')):
                return "格式错误,请使用: PKTracker 任务详情 [任务名称]"
            task_name = parts[2][1:-1]
            return self.task_manager.get_task_detail(group_id, task_name)

        # 处理积分详情命令
        elif command == "积分详情":
            page = 1
            user_name = None

            # 解析参数
            for part in parts[2:]:
                if part.startswith('p[') and part.endswith(']'):
                    try:
                        page = int(part[2:-1])
                        if page < 1:
                            return "❌ 页码必须大于0"
                    except ValueError:
                        return "❌ 页码必须是正整数"
                elif part.startswith('[') and part.endswith(']'):
                    user_name = part[1:-1]

            # 根据参数返回相应的积分详情
            if user_name:
                return self.ranking_manager.get_user_bonus_detail(group_id, user_name=user_name, page=page)
            else:
                return self.ranking_manager.get_user_bonus_detail(group_id, sender_id=user_id, page=page)
        # 处理设置连续打卡命令
        elif command == "设置连续打卡":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以设置连续打卡规则"

            if len(parts) < 4:
                return "格式错误,请使用: PKTracker 设置连续打卡 [任务名称] s[开/关] b[分数]"

            task_name = parts[2][1:-1]
            enable = None
            bonus = None

            # 解析参数
            for part in parts[3:]:
                if part.startswith('s[') and part.endswith(']'):
                    status = part[2:-1]
                    if status == "开":
                        enable = 1
                    elif status == "关":
                        enable = 0
                    else:
                        return "❌ 状态必须是 开 或 关"
                elif part.startswith('b[') and part.endswith(']'):
                    try:
                        bonus = int(part[2:-1])
                        if bonus < 0:
                            return "❌ 分数必须大于等于0"
                    except ValueError:
                        return "❌ 分数必须是整数"

            if enable is None:
                return "❌ 请设置连续打卡状态：s[开] 或 s[关]"

            if enable == 1 and bonus is None:
                return "❌ 开启连续打卡时必须设置分数"

            return self.task_manager.set_continuous_checkin(group_id, task_name, enable, bonus)
        # 处理设置首次打卡命令
        elif command == "设置首次打卡":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以设置首次打卡规则"

            if len(parts) < 4:
                return "格式错误,请使用: PKTracker 设置首次打卡 [任务名称] s[开/关] b[分数]"

            task_name = parts[2][1:-1]
            enable = None
            bonus = None

            # 解析参数
            for part in parts[3:]:
                if part.startswith('s[') and part.endswith(']'):
                    status = part[2:-1]
                    if status == "开":
                        enable = 1
                    elif status == "关":
                        enable = 0
                    else:
                        return "❌ 状态必须是 开 或 关"
                elif part.startswith('b[') and part.endswith(']'):
                    try:
                        bonus = int(part[2:-1])
                        if bonus < 0:
                            return "❌ 分数必须大于等于0"
                    except ValueError:
                        return "❌ 分数必须是整数"

            if enable is None:
                return "❌ 请设置首次打卡状态：s[开] 或 s[关]"

            if enable == 1 and bonus is None:
                return "❌ 开启首次打卡时必须设置分数"

            return self.task_manager.set_first_checkin(group_id, task_name, enable, bonus)
        # 处理设置周冠军命令
        elif command == "设置周冠军":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以设置周冠军规则"

            if len(parts) < 4:
                return "格式错误,请使用: PKTracker 设置周冠军 [任务名称] s[开/关] b[分数]"

            task_name = parts[2][1:-1]
            enable = None
            bonus = None

            # 解析参数
            for part in parts[3:]:
                if part.startswith('s[') and part.endswith(']'):
                    status = part[2:-1]
                    if status == "开":
                        enable = 1
                    elif status == "关":
                        enable = 0
                    else:
                        return "❌ 状态必须是 开 或 关"
                elif part.startswith('b[') and part.endswith(']'):
                    try:
                        bonus = int(part[2:-1])
                        if bonus < 0:
                            return "❌ 分数必须大于等于0"
                    except ValueError:
                        return "❌ 分数必须是整数"

            if enable is None:
                return "❌ 请设置周冠军状态：s[开] 或 s[关]"

            if enable == 1 and bonus is None:
                return "❌ 开启周冠军时必须设置分数"

            return self.task_manager.set_week_checkin(group_id, task_name, enable, bonus)

        # 处理设置月冠军命令
        elif command == "设置月冠军":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以设置月冠军规则"

            if len(parts) < 4:
                return "格式错误,请使用: PKTracker 设置月冠军 [任务名称] s[开/关] b[分数]"

            task_name = parts[2][1:-1]
            enable = None
            bonus = None

            # 解析参数
            for part in parts[3:]:
                if part.startswith('s[') and part.endswith(']'):
                    status = part[2:-1]
                    if status == "开":
                        enable = 1
                    elif status == "关":
                        enable = 0
                    else:
                        return "❌ 状态必须是 开 或 关"
                elif part.startswith('b[') and part.endswith(']'):
                    try:
                        bonus = int(part[2:-1])
                        if bonus < 0:
                            return "❌ 分数必须大于等于0"
                    except ValueError:
                        return "❌ 分数必须是整数"

            if enable is None:
                return "❌ 请设置月冠军状态：s[开] 或 s[关]"

            if enable == 1 and bonus is None:
                return "❌ 开启月冠军时必须设置分数"

            return self.task_manager.set_month_checkin(group_id, task_name, enable, bonus)
        # 处理设置任务命令
        elif command == "设置任务":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以设置任务"

            if len(parts) < 4:
                return "格式错误,请使用: PKTracker 设置任务 [任务名称] s[开/关] b[分数]"

            task_name = parts[2][1:-1]
            enable = None
            score = None

            # 解析参数
            for part in parts[3:]:
                if part.startswith('s[') and part.endswith(']'):
                    status = part[2:-1]
                    if status == "开":
                        enable = 1
                    elif status == "关":
                        enable = 0
                    else:
                        return "❌ 状态必须是 开 或 关"
                elif part.startswith('b[') and part.endswith(']'):
                    try:
                        score = int(part[2:-1])
                        if score < 0:
                            return "❌ 分数必须大于等于0"
                    except ValueError:
                        return "❌ 分数必须是整数"

            if enable is None:
                return "❌ 请设置任务状态：s[开] 或 s[关]"

            if enable == 1 and score is None:
                return "❌ 开启任务时必须设置基础分数"

            return self.task_manager.set_task_base_score(group_id, task_name, enable, score)
        # 处理删除任务命令
        elif command == "删除任务":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以删除任务"

            if len(parts) != 3 or not (parts[2].startswith('[') and parts[2].endswith(']')):
                return "格式错误,请使用: PKTracker 删除任务 [任务名称]"

            task_name = parts[2][1:-1]
            return self.task_manager.delete_task(group_id, task_name)
            # 处理设置提醒时间命令
        elif command == "设置提醒时间":
            if not self.admin_manager.is_admin(group_id, user_id):
                return "只有管理员可以设置提醒时间"

            if len(parts) < 4:
                return "格式错误,请使用: PKTracker 设置提醒时间 [任务名称] time[提醒时间] t[提醒内容]"

            task_name = parts[2][1:-1]
            reminder_time = None
            remind_text = None

            # 解析参数
            for part in parts[3:]:
                if part.startswith('time[') and part.endswith(']'):
                    reminder_time = part[5:-1]
                elif part.startswith('t[') and part.endswith(']'):
                    remind_text = part[2:-1]

            if reminder_time is None:
                return "❌ 请设置提醒时间：time[HH:MM]"

            return self.task_manager.set_reminder(group_id, task_name, reminder_time, remind_text)
        else:
            return "未知命令,请检查输入"

    def get_help_text(self, **kwargs):
        base_help = """📝 微信群打卡PK插件使用指南

    🔹 基础打卡指令:
      PKTracker [任务名称] 打卡内容
      例如: PKTracker [早起] 今天6点起床啦

    🔹 查看任务:
      - 查看任务列表:
        PKTracker 任务列表
      - 查看任务详情:
        PKTracker 任务详情 [任务名称]
      - 查看指定任务排名:
        PKTracker 积分榜 [任务名称]
      - 查看所有任务排名:
        PKTracker 积分榜
      - 查看积分详情:
        PKTracker 积分详情 [用户名] p[页码]
        例如: 
        PKTracker 积分详情          (查看自己的第1页)
        PKTracker 积分详情 p[2]     (查看自己的第2页)
        PKTracker 积分详情 [张三]    (查看张三的第1页)
        PKTracker 积分详情 [张三] p[2] (查看张三的第2页)

    🔹 管理员指令:
      1. 任务管理:
         - 创建任务:
           PKTracker 创建任务 [任务名称]
         - 删除任务:
           PKTracker 删除任务 [任务名称]
         - 设置任务状态和基础分:
           PKTracker 设置任务 [任务名称] s[开/关] b[分数]
           例如: PKTracker 设置任务 [早起] s[开] b[2]
         - 设置打卡次数:
           PKTracker 设置次数 [任务名称] [次数]
           例如: PKTracker 设置次数 [早起] [3]

      2. 提醒设置:
         - 设置提醒时间:
           PKTracker 设置提醒时间 [任务名称] time[HH:MM] t[提醒内容]
           例如: PKTracker 设置提醒时间 [早起] time[07:00] t[该起床打卡啦]

      3. 奖励设置:
         - 设置连续打卡奖励:
           PKTracker 设置连续打卡 [任务名称] s[开/关] b[分数]
         - 设置首次打卡奖励:
           PKTracker 设置首次打卡 [任务名称] s[开/关] b[分数]
         - 设置周冠军奖励:
           PKTracker 设置周冠军 [任务名称] s[开/关] b[分数]
         - 设置月冠军奖励:
           PKTracker 设置月冠军 [任务名称] s[开/关] b[分数]

      4. 管理员管理:
         - 查看管理员:
           PKTracker 查看管理员
         - 添加管理员(仅超管):
           PKTracker 添加管理员 [用户名]
         - 取消管理员(仅超管):
           PKTracker 取消管理员 [用户名]

    🔸 系统功能:
      - 每日排行榜: 每天早上9:10自动发送
      - 周冠军公告: 每周日晚23:00自动结算
      - 月冠军公告: 每月最后一天23:00自动结算
      - 定时提醒: 根据设置的提醒时间自动发送

    💡 Tips: 
      - 每个任务可以设置每日打卡次数限制
      - 任务可以分别开启/关闭各种奖励机制
      - 基础分数、连续打卡、首次打卡等奖励分数都可自定义
      - 打卡内容要认真填写哦~
      - 管理员可以通过任务详情查看具体设置"""

        return base_help

    def on_unload(self):
        """插件卸载时的清理工作"""
        try:
            if PKTracker._scheduler_initialized and hasattr(self, 'scheduler'):
                self.scheduler.stop_scheduler()
                PKTracker._scheduler_initialized = False
                PKTracker._instance = None
                logger.info("[PKTracker] 插件卸载，调度器已停止")
        except Exception as e:
            logger.error(f"[PKTracker] 插件卸载异常: {str(e)}")
