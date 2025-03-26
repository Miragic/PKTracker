import sqlite3
from datetime import datetime, timedelta

from common.log import logger


class CheckinManager:
    def __init__(self, db_path):
        self.db_path = db_path

    def handle_checkin(self, user_id, group_id, task_name, content):
        """处理打卡"""
        global conn
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id, frequency, max_checkins FROM t_task 
                        WHERE group_id=? AND task_name=? AND enable=1""",
                      (group_id, task_name))
            task = c.fetchone()
            if not task:
                return f"任务 [{task_name}] 不存在或未启用"

            task_id, frequency, max_checkins = task
            now = datetime.now()

            # 根据频率检查打卡次数
            if frequency == 'day':
                date_start = now.strftime('%Y-%m-%d 00:00:00')
                date_end = now.strftime('%Y-%m-%d 23:59:59')
            elif frequency == 'week':
                # 获取本周一和下周一的日期
                monday = now - timedelta(days=now.weekday())
                date_start = monday.strftime('%Y-%m-%d 00:00:00')
                date_end = (monday + timedelta(days=6)).strftime('%Y-%m-%d 23:59:59')
            else:  # month
                # 获取本月第一天和最后一天
                first_day = now.replace(day=1)
                if now.month == 12:
                    last_day = now.replace(year=now.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    last_day = now.replace(month=now.month + 1, day=1) - timedelta(days=1)
                date_start = first_day.strftime('%Y-%m-%d 00:00:00')
                date_end = last_day.strftime('%Y-%m-%d 23:59:59')

            # 检查当前周期内的打卡次数
            c.execute("""SELECT COUNT(*) FROM t_checkin_log 
                        WHERE task_id=? AND user_id=? 
                        AND datetime(checkin_time) >= datetime(?)
                        AND datetime(checkin_time) <= datetime(?)""",
                      (task_id, user_id, date_start, date_end))
            current_checkins = c.fetchone()[0]

            if max_checkins > 0 and current_checkins >= max_checkins:
                period_map = {'day': '今日', 'week': '本周', 'month': '本月'}
                return f"❌ {period_map[frequency]}已达到最大打卡次数 ({max_checkins}次)"

            # 记录打卡
            c.execute("""INSERT INTO t_checkin_log (task_id, user_id, checkin_time, content)
                        VALUES (?, ?, ?, ?)""",
                      (task_id, user_id, now.strftime('%Y-%m-%d %H:%M:%S'), content))
            checkin_id = c.lastrowid

            # 计算奖励
            bonus_details = self._calculate_bonus(c, task_id, user_id, now)

            # 记录积分明细
            for bonus_type, bonus_value in bonus_details.items():
                if bonus_value > 0:
                    c.execute("""INSERT INTO t_bonus 
                                (task_id, user_id, checkin_id, bonus_type, bonus_value, create_time)
                                VALUES (?, ?, ?, ?, ?, ?)""",
                              (task_id, user_id, checkin_id, bonus_type, bonus_value,
                               now.strftime('%Y-%m-%d %H:%M:%S')))

            total_bonus = sum(bonus_details.values())
            conn.commit()

            # 生成积分明细消息
            bonus_msg = "\n".join([
                f"🎯 {desc}: +{value}分" for desc, value in [
                    ("基础打卡", bonus_details.get("base", 0)),
                    ("首次打卡", bonus_details.get("first", 0)),
                    ("连续打卡", bonus_details.get("consecutive", 0))
                ] if value > 0
            ])

            return f"""✅ 打卡成功!
{bonus_msg}
━━━━━━━━━━
💫 总计: {total_bonus}分"""

        except Exception as e:
            logger.exception(f"[PKTracker] 打卡异常: {str(e)}")
            return "❌ 打卡失败,请稍后重试"
        finally:
            if 'conn' in locals() and conn is not None:
                conn.close()

    def _calculate_bonus(self, cursor, task_id, user_id, checkin_time):
        """计算打卡奖励"""
        bonus = {
            "base": 1,  # 基础打卡积分
            "first": 0,  # 首次打卡奖励
            "consecutive": 0  # 连续打卡奖励
        }

        # 获取任务配置
        cursor.execute("""SELECT first_checkin_reward_enabled, first_checkin_reward,
                         consecutive_checkin_reward_enabled, consecutive_checkin_reward
                         FROM t_task WHERE task_id=?""", (task_id,))
        task_info = cursor.fetchone()

        # 检查首次打卡奖励
        if task_info[0]:  # first_checkin_reward_enabled
            today = checkin_time.date()
            cursor.execute("""SELECT COUNT(*) FROM t_checkin_log 
                            WHERE task_id=? AND date(checkin_time)=?""",
                           (task_id, today))
            if cursor.fetchone()[0] == 1:
                bonus["first"] = task_info[1]  # first_checkin_reward

        # 检查连续打卡奖励
        if task_info[2]:  # consecutive_checkin_reward_enabled
            cursor.execute("""SELECT date(checkin_time) FROM t_checkin_log
                            WHERE task_id=? AND user_id=?
                            ORDER BY checkin_time DESC LIMIT 3""",
                           (task_id, user_id))
            dates = cursor.fetchall()

            if len(dates) == 3:
                date1 = datetime.strptime(dates[0][0], '%Y-%m-%d')
                date2 = datetime.strptime(dates[1][0], '%Y-%m-%d')
                date3 = datetime.strptime(dates[2][0], '%Y-%m-%d')

                if (date1 - date2).days == 1 and (date2 - date3).days == 1:
                    bonus["consecutive"] = task_info[3]  # consecutive_checkin_reward

        return bonus
