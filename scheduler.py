import gc
import sqlite3
import threading
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config as RobotConfig
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel import channel_factory
from channel.chat_message import ChatMessage
from common.log import logger


class TaskScheduler:
    _instance = None
    _initialized = False
    _scheduler = None
    _lock = threading.Lock()
    _jobs_initialized = False  # 新增标志位

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, db_path, user_manager):
        with self._lock:
            if not TaskScheduler._initialized:
                self.db_path = db_path
                self.channel = None
                self.user_manager = user_manager

                if TaskScheduler._scheduler is None:
                    TaskScheduler._scheduler = BackgroundScheduler(
                        timezone='Asia/Shanghai',
                        job_defaults={
                            'coalesce': True,
                            'max_instances': 1,
                            'misfire_grace_time': 60
                        },
                        executors={
                            'default': {
                                'type': 'threadpool',
                                'max_workers': 1
                            }
                        }
                    )
                    # 只在第一次初始化时添加任务
                    if not TaskScheduler._jobs_initialized:
                        self._init_scheduler()
                        TaskScheduler._jobs_initialized = True
                self.scheduler = TaskScheduler._scheduler
                TaskScheduler._initialized = True

    def _init_scheduler(self):
        """初始化定时任务"""
        with self._lock:
            # 确保调度器是干净的状态
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            self.scheduler.remove_all_jobs()

            # 添加新任务，使用固定的任务ID
            self.scheduler.add_job(
                self.check_reminders,
                CronTrigger(minute='*'),
                id='check_reminders',
                replace_existing=True,
                max_instances=1
            )

        # 从配置文件获取每日排行榜发送时间
        daily_ranking_time = self.user_manager.config.get("daily_ranking_time")  # 从配置文件获取时间
        if daily_ranking_time:  # 只有在设置了时间时才添加定时任务
            try:
                hour, minute = map(int, daily_ranking_time.split(':'))
                self.scheduler.add_job(
                    self.send_daily_ranking,
                    CronTrigger(hour=hour, minute=minute),
                    id='daily_ranking'
                )
                logger.info(f"[PKTracker] 每日排行榜定时任务已设置: {daily_ranking_time}")
            except Exception as e:
                logger.error(f"[PKTracker] 设置每日排行榜定时任务失败: {str(e)}")

        # 每周晚上23:00处理周奖励
        self.scheduler.add_job(
            self.process_weekly_rewards,
            CronTrigger(day_of_week='sun', hour=23),
            id='weekly_rewards'
        )

        # 每月最后一天23:00处理月奖励
        self.scheduler.add_job(
            self.process_monthly_rewards,
            CronTrigger(day='last', hour=23),
            id='monthly_rewards'
        )

    def check_reminders(self):
        """检查并触发到期的提醒"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            now = datetime.now()
            current_time = now.strftime('%H:%M')

            # 获取所有启用的任务
            c.execute("""
                SELECT t.task_id, t.group_id, t.task_name, t.reminder_time, t.remind_text,
                       COUNT(DISTINCT cl.user_id) as checked_users
                FROM t_task t
                LEFT JOIN t_checkin_log cl ON t.task_id = cl.task_id 
                    AND date(cl.checkin_time) = date('now')
                WHERE t.enable = 1 
                    AND t.reminder_time = ?
                    AND t.reminder_time IS NOT NULL
                GROUP BY t.task_id
            """, (current_time,))

            tasks = c.fetchall()
            # 打印tasks的size
            logger.info(f"[PKTracker] 当前时间: {current_time}, 任务数量: {len(tasks)}")

            for task in tasks:
                task_id, group_id, task_name, reminder_time, remind_text, checked_users = task

                # 构建提醒消息
                message = f"⏰ 任务提醒 [{task_name}]\n"
                message += "===================\n\n"

                if remind_text:
                    message += f"📝 {remind_text}\n\n"

                message += f"🔸 今日已打卡: {checked_users}人\n"
                message += "\n💡 快来打卡啦~记得使用以下格式:\n"
                message += f"PKTracker [{task_name}] 打卡内容"

                # 发送提醒消息
                self._send_reminder(group_id, message)

                logger.info(f"[PKTracker] 已发送任务 [{task_name}] 的提醒消息到群组 {group_id}")

        except Exception as e:
            logger.error(f"[PKTracker] 检查提醒异常: {str(e)}")
        finally:
            if conn:
                conn.close()

    def _send_reminder(self, group_id: str, message: str):
        """发送提醒消息"""
        try:
            # 构建消息上下文
            context = Context(ContextType.TEXT, message)
            context["isgroup"] = True
            context["group_id"] = group_id
            context["receiver"] = group_id

            # 构建完整的消息对象
            msg = ChatMessage(None)
            msg.is_group = True
            msg.other_user_id = group_id
            msg.to_user_id = group_id
            msg.actual_user_id = group_id
            context["msg"] = msg

            # 构建回复消息
            reply = Reply(ReplyType.TEXT, message)

            # 获取当前 channel 类型并创建 channel
            channel_name = RobotConfig.conf().get("channel_type", "wx")
            channel = channel_factory.create_channel(channel_name)

            # 发送消息
            channel.send(reply, context)

            logger.info(f"[PKTracker] 成功发送消息到群组 {group_id}")
            return True
        except Exception as e:
            logger.error(f"[PKTracker] 发送提醒消息失败: {str(e)}")
            return False

    def process_weekly_rewards(self):
        """处理每周奖励"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 获取所有启用周奖励的任务
            c.execute("""
                SELECT t.task_id, t.group_id, t.task_name, t.week_checkin_reward
                FROM t_task t
                WHERE t.enable = 1 
                    AND t.week_checkin_reward_enabled = 1
                    AND t.week_checkin_reward IS NOT NULL
            """)

            tasks = c.fetchall()
            for task_id, group_id, task_name, bonus in tasks:
                # 获取本周打卡次数最多的用户
                c.execute("""
                    SELECT 
                        user_id,
                        COUNT(*) as checkin_count
                    FROM t_checkin_log
                    WHERE task_id = ? 
                        AND checkin_time >= date('now', 'weekday 0', '-7 days')
                        AND checkin_time < date('now', 'weekday 0')
                    GROUP BY user_id
                    ORDER BY checkin_count DESC
                    LIMIT 1
                """, (task_id,))

                winner = c.fetchone()
                if winner:
                    user_id, checkin_count = winner
                    # 批量获取用户昵称
                    nicknames = self.user_manager._get_nickname_by_user_ids([user_id])
                    user_name = nicknames.get(user_id, "未知用户")

                    # 记录奖励
                    c.execute("""
                        INSERT INTO t_bonus (task_id, user_id, type, amount, date_awarded)
                        VALUES (?, ?, 'week', ?, date('now'))
                    """, (task_id, user_id, bonus))

                    # 发送获奖通知
                    message = f"🎉 周冠军公告 [{task_name}]\n"
                    message += "===================\n\n"
                    message += f"👑 本周冠军: {user_name}\n"
                    message += f"📊 打卡次数: {checkin_count}次\n"
                    message += f"🎁 奖励积分: {bonus}分\n"
                    message += "\n继续加油,下周等你来战！💪"

                    self._send_reminder(group_id, message)

            conn.commit()

        except Exception as e:
            logger.error(f"[PKTracker] 处理周奖励异常: {str(e)}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def process_monthly_rewards(self):
        """处理每月奖励"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 获取所有启用月奖励的任务
            c.execute("""
                SELECT t.task_id, t.group_id, t.task_name, t.month_checkin_reward
                FROM t_task t
                WHERE t.enable = 1 
                    AND t.month_checkin_reward_enabled = 1
                    AND t.month_checkin_reward IS NOT NULL
            """)

            tasks = c.fetchall()
            for task_id, group_id, task_name, bonus in tasks:
                # 获取上月打卡次数最多的用户
                c.execute("""
                    SELECT 
                        user_id,
                        COUNT(*) as checkin_count
                    FROM t_checkin_log
                    WHERE task_id = ? 
                        AND checkin_time >= date('now', 'start of month', '-1 month')
                        AND checkin_time < date('now', 'start of month')
                    GROUP BY user_id
                    ORDER BY checkin_count DESC
                    LIMIT 1
                """, (task_id,))

                winner = c.fetchone()
                if winner:
                    user_id, checkin_count = winner
                    # 批量获取用户昵称
                    nicknames = self.user_manager._get_nickname_by_user_ids([user_id])
                    user_name = nicknames.get(user_id, "未知用户")

                    # 记录奖励
                    c.execute("""
                        INSERT INTO t_bonus (task_id, user_id, type, amount, date_awarded)
                        VALUES (?, ?, 'month', ?, date('now'))
                    """, (task_id, user_id, bonus))

                    # 发送获奖通知
                    message = f"🎉 月度冠军公告 [{task_name}]\n"
                    message += "===================\n\n"
                    message += f"👑 本月冠军: {user_name}\n"
                    message += f"📊 打卡次数: {checkin_count}次\n"
                    message += f"🎁 奖励积分: {bonus}分\n"
                    message += "\n继续加油,下月等你来战！💪"

                    self._send_reminder(group_id, message)

            conn.commit()

        except Exception as e:
            logger.error(f"[PKTracker] 处理月奖励异常: {str(e)}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def send_ranking_list(self, task_id):
        """发送任务排行榜"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 获取任务信息
            c.execute("""
                SELECT group_id, task_name 
                FROM t_task 
                WHERE task_id = ?
            """, (task_id,))

            task = c.fetchone()
            if not task:
                logger.error(f"[PKTracker] 未找到任务ID: {task_id}")
                return

            group_id, task_name = task

            # 获取排行榜数据
            c.execute("""
                WITH checkin_stats AS (
                    -- 计算基础打卡次数和对应的基础积分
                    SELECT 
                        cl.user_id,
                        COUNT(*) as checkin_count,
                        SUM(COALESCE(
                            (SELECT b.bonus_value 
                             FROM t_bonus b 
                             WHERE b.checkin_id = cl.checkin_id 
                             AND b.bonus_type = 'base'), 0)
                        ) as base_points,
                        SUM(COALESCE(
                            (SELECT b.bonus_value 
                             FROM t_bonus b 
                             WHERE b.checkin_id = cl.checkin_id 
                             AND b.bonus_type = 'first'), 0)
                        ) as first_points,
                        SUM(COALESCE(
                            (SELECT b.bonus_value 
                             FROM t_bonus b 
                             WHERE b.checkin_id = cl.checkin_id 
                             AND b.bonus_type = 'consecutive'), 0)
                        ) as consecutive_points,
                        SUM(COALESCE(
                            (SELECT b.bonus_value 
                             FROM t_bonus b 
                             WHERE b.checkin_id = cl.checkin_id 
                             AND b.bonus_type IN ('week', 'month')), 0)
                        ) as special_points
                    FROM t_checkin_log cl
                    WHERE cl.task_id = ?
                    GROUP BY cl.user_id
                )
                SELECT 
                    user_id,
                    checkin_count,
                    base_points,
                    first_points,
                    consecutive_points,
                    special_points,
                    (base_points + first_points + consecutive_points + special_points) as total_points
                FROM checkin_stats
                ORDER BY total_points DESC, checkin_count DESC
                LIMIT 10
            """, (task_id,))

            rankings = c.fetchall()

            # 批量获取用户昵称
            user_ids = [user_id for user_id, *_ in rankings]
            nicknames = self.user_manager._get_nickname_by_user_ids(user_ids)

            # 生成排行榜消息
            message = f"📊 [{task_name}] 排行榜 TOP 10\n"
            message += "===================\n\n"
            for idx, (user_id, checkins, base, first, consec, special, total) in enumerate(rankings, 1):
                name = nicknames.get(user_id, "未知用户")
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else "👑"

                message += f"{medal} {idx}. {name}\n"
                message += f"   打卡: {checkins}次 | 总积分: {total}\n"
                message += f"   (基础:{base} 首次:{first} 连续:{consec} 奖励:{special})\n"

            # 发送消息
            self._send_reminder(group_id, message)
            logger.info(f"[PKTracker] 已发送任务 [{task_name}] 的排行榜")

        except Exception as e:
            logger.error(f"[PKTracker] 发送排行榜异常: {str(e)}")
        finally:
            if conn:
                conn.close()

    def send_daily_ranking(self):
        """发送每日任务排行榜"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 获取所有启用的任务
            c.execute("""
                SELECT task_id, group_id, task_name
                FROM t_task
                WHERE enable = 1
            """)

            tasks = c.fetchall()
            for task_id, group_id, task_name in tasks:
                # 调用现有的排行榜发送方法
                self.send_ranking_list(task_id)
                logger.info(f"[PKTracker] 已发送任务 [{task_name}] 的每日排行榜")

        except Exception as e:
            logger.error(f"[PKTracker] 发送每日排行榜异常: {str(e)}")
        finally:
            if conn:
                conn.close()
