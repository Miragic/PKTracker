import sqlite3
from datetime import datetime

from common.log import logger


class TaskManager:
    def __init__(self, db_path):
        self.db_path = db_path

    def set_frequency(self, group_id: str, task_name: str, frequency: str) -> str:
        """设置任务打卡频率"""
        # 验证频率参数
        freq_map = {"日": "day", "周": "week", "月": "month"}
        if frequency not in freq_map:
            return "❌ 频率设置失败: 频率只能是 日/周/月"

        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在，请先创建任务"

            # 更新任务频率
            c.execute("""UPDATE t_task 
                        SET frequency=? 
                        WHERE group_id=? AND task_name=?""",
                      (freq_map[frequency], group_id, task_name))

            conn.commit()
            result = f"✅ 成功设置任务 [{task_name}] 的打卡频率为: {frequency}\n\n"
            result += self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 设置任务频率异常: {str(e)}")
            return "❌ 设置失败,请稍后重试"
        finally:
            conn.close()

    def get_task_list(self, group_id: str) -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            c.execute("""
                SELECT t.task_name, t.frequency, t.max_checkins,
                       COUNT(cl.checkin_id) as total_checkins,
                       t.consecutive_checkin_reward_enabled, t.consecutive_checkin_reward,
                       t.first_checkin_reward_enabled, t.first_checkin_reward,
                       t.week_checkin_reward_enabled, t.week_checkin_reward,
                       t.month_checkin_reward_enabled, t.month_checkin_reward,
                       t.enable, t.base_score,t.reminder_time,t.remind_text
                FROM t_task t
                LEFT JOIN t_checkin_log cl ON t.task_id = cl.task_id
                WHERE t.group_id=?
                GROUP BY t.task_id
                ORDER BY t.task_id DESC
            """, (group_id,))

            tasks = c.fetchall()
            if not tasks:
                return "当前群组暂无任务"

            message = "📝 任务列表\n==================="

            freq_map = {"day": "每日", "week": "每周", "month": "每月"}
            for (task_name, frequency, max_checkins, total_checkins,
                 continuous_enable, continuous_bonus,
                 first_enable, first_bonus,
                 weekly_enable, weekly_bonus,
                 monthly_enable, monthly_bonus,
                 task_enable, base_score, reminder_time, remind_text) in tasks:
                freq_text = freq_map.get(frequency, frequency)
                message += f"\n\n{'✅' if task_enable else '❌'} [{task_name}]"
                message += f" ({('已启用' if task_enable else '已禁用')})"
                message += f"\n🔸 打卡频率: {freq_text}"
                message += f"\n🔸 基础分数: {base_score}分\n"
                if reminder_time:
                    message += f"   - 提醒时间: {reminder_time}\n"
                    if remind_text:
                        message += f"   - 提醒内容: {remind_text}\n"
                message += f"\n🔸 总打卡次数: {total_checkins}次"
                message += f"\n🔸 最大打卡次数: {max_checkins}次"
                message += "\n🔸 奖励设置:"
                message += f"\n   - 首次打卡: {'开启 (+' + str(first_bonus) + '分)' if first_enable else '关闭'}"
                message += f"\n   - 连续打卡: {'开启 (+' + str(continuous_bonus) + '分)' if continuous_enable else '关闭'}"
                message += f"\n   - 周冠军: {'开启 (+' + str(weekly_bonus) + '分)' if weekly_enable else '关闭'}"
                message += f"\n   - 月冠军: {'开启 (+' + str(monthly_bonus) + '分)' if monthly_enable else '关闭'}"

            return message

        except Exception as e:
            logger.exception(f"[PKTracker] 获取任务列表异常: {str(e)}")
            return "❌ 获取任务列表失败"
        finally:
            conn.close()

    def set_max_checkins(self, group_id: str, task_name: str, max_checkins: int) -> str:
        """设置任务打卡次数限制"""
        if max_checkins < 1:
            return "❌ 打卡次数必须大于0"

        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在"

            # 更新打卡次数
            c.execute("""UPDATE t_task 
                        SET max_checkins=? 
                        WHERE group_id=? AND task_name=?""",
                      (max_checkins, group_id, task_name))

            conn.commit()
            result = f"✅ 成功设置任务 [{task_name}] 的最大打卡次数为: {max_checkins}\n\n"
            result += self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 设置打卡次数异常: {str(e)}")
            return "❌ 设置失败,请稍后重试"
        finally:
            conn.close()

    def create_task(self, group_id: str, task_name: str) -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务名是否已存在
            c.execute("""SELECT 1 FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if c.fetchone():
                return f"❌ 任务 [{task_name}] 已存在"

            # 创建新任务,设置默认值
            c.execute("""INSERT INTO t_task 
                        (group_id, task_name, frequency, max_checkins, enable) 
                        VALUES (?, ?, 'day', 1, 1)""",
                      (group_id, task_name))
            conn.commit()

            # 获取任务信息
            c.execute("""SELECT frequency, max_checkins FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            frequency, max_checkins = c.fetchone()

            freq_map = {'day': '每日', 'week': '每周', 'month': '每月'}
            freq_text = freq_map.get(frequency, frequency)
            checkins_text = f"每{freq_text}最多打卡{max_checkins}次" if max_checkins > 0 else "不限制打卡次数"

            return f"""✅ 创建任务成功!
任务名称: [{task_name}]
打卡频率: {freq_text}
打卡限制: {checkins_text}

{self.get_task_list(group_id)}"""

        except Exception as e:
            logger.exception(f"[PKTracker] 创建任务异常: {str(e)}")
            return "❌ 创建任务失败,请稍后重试"
        finally:
            conn.close()

    def get_task_detail(self, group_id: str, task_name: str) -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 获取任务基本信息
            c.execute("""
                SELECT t.task_id, t.frequency, t.max_checkins,
                       COUNT(DISTINCT cl.user_id) as total_users,
                       COUNT(cl.checkin_id) as total_checkins,
                       MAX(cl.checkin_time) as last_checkin,
                       t.first_checkin_reward_enabled, t.first_checkin_reward,
                       t.consecutive_checkin_reward_enabled, t.consecutive_checkin_reward,
                       t.week_checkin_reward_enabled, t.week_checkin_reward,
                       t.month_checkin_reward_enabled, t.month_checkin_reward,
                       t.enable, t.base_score, t.reminder_time,t.remind_text
                FROM t_task t
                LEFT JOIN t_checkin_log cl ON t.task_id = cl.task_id
                WHERE t.group_id=? AND t.task_name=?
                GROUP BY t.task_id
            """, (group_id, task_name))

            task = c.fetchone()
            if not task:
                return f"❌ 任务 [{task_name}] 不存在"

            (task_id, frequency, max_checkins, total_users, total_checkins, last_checkin,
             first_enable, first_bonus, continuous_enable, continuous_bonus,
             weekly_enable, weekly_bonus, monthly_enable, monthly_bonus,
             task_enable, base_score, reminder_time, remind_text) = task

            # 获取今日打卡人数
            today = datetime.now().strftime('%Y-%m-%d')
            c.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM t_checkin_log
                WHERE task_id=? AND date(checkin_time)=?
            """, (task_id, today))
            today_users = c.fetchone()[0]

            # 获取连续打卡人数
            c.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM (
                    SELECT user_id, COUNT(*) as consecutive_days
                    FROM t_checkin_log
                    WHERE task_id=? AND checkin_time >= date('now', '-3 days')
                    GROUP BY user_id
                    HAVING consecutive_days >= 3
                )
            """, (task_id,))
            consecutive_users = c.fetchone()[0]

            freq_map = {"day": "每日", "week": "每周", "month": "每月"}
            freq_text = freq_map.get(frequency, frequency)

            message = f"📊 任务详情 [{task_name}]\n"
            message += "===================\n\n"
            message += f"🔸 任务状态: {'已启用 ✅' if task_enable else '已禁用 ❌'}\n\n"
            message += f"🔸 基本信息:\n"
            message += f"   - 打卡频率: {freq_text}\n"
            message += f"   - 基础分数: {base_score}分\n"
            message += f"   - 最大打卡次数: {max_checkins}次/{freq_text}\n"
            if reminder_time:
                message += f"   - 提醒时间: {reminder_time}\n"
                if remind_text:
                    message += f"   - 提醒内容: {remind_text}\n"
            message += f"   - 首次打卡: {'开启 (+' + str(first_bonus) + '分)' if first_enable else '关闭'}\n"
            message += f"   - 连续打卡: {'开启 (+' + str(continuous_bonus) + '分)' if continuous_enable else '关闭'}\n"
            message += f"   - 周冠军: {'开启 (+' + str(weekly_bonus) + '分)' if weekly_enable else '关闭'}\n"
            message += f"   - 月冠军: {'开启 (+' + str(monthly_bonus) + '分)' if monthly_enable else '关闭'}\n\n"
            message += f"🔸 统计信息:\n"
            message += f"   - 参与总人数: {total_users}人\n"
            message += f"   - 总打卡次数: {total_checkins}次\n"
            message += f"   - 今日打卡人数: {today_users}人\n"
            message += f"   - 连续打卡达标: {consecutive_users}人\n"
            if last_checkin:
                message += f"   - 最后打卡时间: {last_checkin}\n"

            return message

        except Exception as e:
            logger.exception(f"[PKTracker] 获取任务详情异常: {str(e)}")
            return "❌ 获取任务详情失败"
        finally:
            conn.close()

    def set_first_checkin(self, group_id: str, task_name: str, enable: int, bonus: int = None) -> str:
        """设置任务首次打卡奖励
        
        Args:
            group_id: 群组ID
            task_name: 任务名称
            enable: 是否启用 (1: 启用, 0: 禁用)
            bonus: 奖励分数
            
        Returns:
            str: 设置结果信息
        """
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在"

            # 更新首次打卡设置
            if enable == 1:
                c.execute("""UPDATE t_task 
                            SET first_checkin_reward_enabled=?, first_checkin_reward=?
                            WHERE group_id=? AND task_name=?""",
                          (enable, bonus, group_id, task_name))
                status_text = f"已开启，奖励 {bonus} 分"
            else:
                c.execute("""UPDATE t_task 
                            SET first_checkin_reward_enabled=?, first_checkin_reward=NULL
                            WHERE group_id=? AND task_name=?""",
                          (enable, group_id, task_name))
                status_text = "已关闭"

            conn.commit()
            result = f"✅ 成功设置任务 [{task_name}] 的首次打卡奖励: {status_text}\n\n"
            result += self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 设置首次打卡奖励异常: {str(e)}")
            return "❌ 设置失败,请稍后重试"
        finally:
            conn.close()

    def set_continuous_checkin(self, group_id: str, task_name: str, enable: int, bonus: int = None) -> str:
        """设置任务连续打卡奖励
        
        Args:
            group_id: 群组ID
            task_name: 任务名称
            enable: 是否启用 (1: 启用, 0: 禁用)
            bonus: 奖励分数
            
        Returns:
            str: 设置结果信息
        """
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在"

            # 更新连续打卡设置
            if enable == 1:
                c.execute("""UPDATE t_task 
                            SET consecutive_checkin_reward_enabled=?, consecutive_checkin_reward=?
                            WHERE group_id=? AND task_name=?""",
                          (enable, bonus, group_id, task_name))
                status_text = f"已开启，奖励 {bonus} 分"
            else:
                c.execute("""UPDATE t_task 
                            SET consecutive_checkin_reward_enabled=?, consecutive_checkin_reward=NULL
                            WHERE group_id=? AND task_name=?""",
                          (enable, group_id, task_name))
                status_text = "已关闭"

            conn.commit()
            result = f"✅ 成功设置任务 [{task_name}] 的连续打卡奖励: {status_text}\n\n"
            result += self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 设置连续打卡奖励异常: {str(e)}")
            return "❌ 设置失败,请稍后重试"
        finally:
            conn.close()

    def set_week_checkin(self, group_id: str, task_name: str, enable: int, bonus: int = None) -> str:
        """设置任务周冠军奖励"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在"

            # 更新周冠军设置
            if enable == 1:
                c.execute("""UPDATE t_task 
                            SET week_checkin_reward_enabled=?, week_checkin_reward=?
                            WHERE group_id=? AND task_name=?""",
                          (enable, bonus, group_id, task_name))
                status_text = f"已开启，奖励 {bonus} 分"
            else:
                c.execute("""UPDATE t_task 
                            SET week_checkin_reward_enabled=?, week_checkin_reward=NULL
                            WHERE group_id=? AND task_name=?""",
                          (enable, group_id, task_name))
                status_text = "已关闭"

            conn.commit()
            result = f"✅ 成功设置任务 [{task_name}] 的周冠军奖励: {status_text}\n\n"
            result += self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 设置周冠军奖励异常: {str(e)}")
            return "❌ 设置失败,请稍后重试"
        finally:
            conn.close()

    def set_month_checkin(self, group_id: str, task_name: str, enable: int, bonus: int = None) -> str:
        """设置任务月冠军奖励"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在"

            # 更新月冠军设置
            if enable == 1:
                c.execute("""UPDATE t_task 
                            SET month_checkin_reward_enabled=?, month_checkin_reward=?
                            WHERE group_id=? AND task_name=?""",
                          (enable, bonus, group_id, task_name))
                status_text = f"已开启，奖励 {bonus} 分"
            else:
                c.execute("""UPDATE t_task 
                            SET month_checkin_reward_enabled=?, month_checkin_reward=NULL
                            WHERE group_id=? AND task_name=?""",
                          (enable, group_id, task_name))
                status_text = "已关闭"

            conn.commit()
            result = f"✅ 成功设置任务 [{task_name}] 的月冠军奖励: {status_text}\n\n"
            result += self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 设置月冠军奖励异常: {str(e)}")
            return "❌ 设置失败,请稍后重试"
        finally:
            conn.close()

    def set_task_base_score(self, group_id: str, task_name: str, enable: int, score: int = None) -> str:
        """设置任务基础分数
        
        Args:
            group_id: 群组ID
            task_name: 任务名称
            enable: 是否启用 (1: 启用, 0: 禁用)
            score: 基础分数
            
        Returns:
            str: 设置结果信息
        """
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在"

            # 更新任务设置
            if enable == 1:
                c.execute("""UPDATE t_task 
                            SET enable=?, base_score=?
                            WHERE group_id=? AND task_name=?""",
                          (enable, score, group_id, task_name))
                status_text = f"已开启，基础分数 {score} 分"
            else:
                c.execute("""UPDATE t_task 
                            SET enable=0
                            WHERE group_id=? AND task_name=?""",
                          (group_id, task_name))
                status_text = "已关闭"

            conn.commit()
            result = f"✅ 成功设置任务 [{task_name}]: {status_text}\n\n"
            result += self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 设置任务基础分数异常: {str(e)}")
            return "❌ 设置失败,请稍后重试"
        finally:
            conn.close()

    def delete_task(self, group_id: str, task_name: str) -> str:
        """删除任务
        
        Args:
            group_id: 群组ID
            task_name: 任务名称
            
        Returns:
            str: 删除结果信息
        """
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在"

            # 删除任务相关的所有数据
            c.execute("""DELETE FROM t_checkin_log 
                        WHERE task_id IN (
                            SELECT task_id FROM t_task 
                            WHERE group_id=? AND task_name=?
                        )""", (group_id, task_name))

            c.execute("""DELETE FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))

            conn.commit()
            result = f"✅ 成功删除任务 [{task_name}]\n\n"
            result += self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 删除任务异常: {str(e)}")
            return "❌ 删除失败,请稍后重试"
        finally:
            conn.close()

    def set_reminder(self, group_id: str, task_name: str, reminder_time: str, remind_text: str = None) -> str:
        """设置任务提醒时间和内容
        
        Args:
            group_id: 群组ID
            task_name: 任务名称
            reminder_time: 提醒时间 (HH:MM)
            remind_text: 提醒内容
            
        Returns:
            str: 设置结果信息
        """
        try:
            # 验证时间格式
            try:
                datetime.strptime(reminder_time, '%H:%M')
            except ValueError:
                return "❌ 时间格式错误，请使用 HH:MM 格式，例如：08:00"

            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查任务是否存在
            c.execute("""SELECT task_id FROM t_task 
                        WHERE group_id=? AND task_name=?""",
                      (group_id, task_name))
            if not c.fetchone():
                return f"❌ 任务 [{task_name}] 不存在"

            # 更新提醒设置
            c.execute("""UPDATE t_task 
                        SET reminder_time=?, remind_text=?
                        WHERE group_id=? AND task_name=?""",
                      (reminder_time, remind_text, group_id, task_name))

            conn.commit()
            result = f"✅ 成功设置任务 [{task_name}] 的提醒:\n"
            result += f"🕐 提醒时间: {reminder_time}\n"
            if remind_text:
                result += f"📝 提醒内容: {remind_text}\n"
            result += "\n" + self.get_task_list(group_id)
            return result

        except Exception as e:
            logger.exception(f"[PKTracker] 设置提醒异常: {str(e)}")
            return "❌ 设置失败,请稍后重试"
        finally:
            conn.close()
