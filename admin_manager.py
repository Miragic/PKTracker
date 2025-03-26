import sqlite3

from common.log import logger


class AdminManager:
    def __init__(self, db_path, config, user_manager):
        self.db_path = db_path
        self.config = config
        self.user_manager = user_manager

    def is_admin(self, group_id, user_id):
        # 检查用户是否是超级管理员
        if user_id in self.config.get("super_admins", []):
            return True

        """检查用户是否为管理员"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT 1 FROM t_admin WHERE group_id=? AND user_id=?",
                  (group_id, user_id))
        result = c.fetchone() is not None
        conn.close()
        return result

    def is_super_admin(self, user_id: str) -> bool:
        """检查用户是否为超级管理员"""
        return user_id in self.config.get("super_admins", [])

    def add_admin(self, group_id: str, user_id: str, operator_id: str, user_name: str) -> str:
        """添加管理员
        Args:
            group_id: 群组ID
            user_id: 被添加的用户ID
            operator_id: 操作者ID
        Returns:
            str: 操作结果提示
        """
        if not self.is_super_admin(operator_id):
            return "❌ 只有超级管理员才能添加管理员"

        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查是否已经是管理员
            c.execute("SELECT 1 FROM t_admin WHERE group_id=? AND user_id=?",
                      (group_id, user_id))
            if c.fetchone():
                return f"❌ 用户 {user_name} 已经是管理员了"

            # 添加管理员
            c.execute("INSERT INTO t_admin (group_id, user_id) VALUES (?, ?)",
                      (group_id, user_id))

            conn.commit()
            admin_list = self.get_admin_list(group_id)
            return f"✅ 已将用户 {user_name} 设置为管理员\n\n{admin_list}"

        except Exception as e:
            logger.exception(f"[PKTracker] 添加管理员异常: {str(e)}")
            return "❌ 添加管理员失败,请稍后重试"
        finally:
            conn.close()

    def remove_admin(self, group_id: str, user_id: str, operator_id: str, user_name: str) -> str:
        """取消管理员
        Args:
            group_id: 群组ID
            user_id: 被取消的用户ID
            operator_id: 操作者ID
            user_name: 用户名称
        Returns:
            str: 操作结果提示
        """
        if not self.is_super_admin(operator_id):
            return "❌ 只有超级管理员才能取消管理员"

        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 检查是否是超级管理员
            if user_id in self.config.get("super_admins", []):
                return "❌ 无法取消超级管理员的权限"

            # 检查是否是管理员
            c.execute("SELECT 1 FROM t_admin WHERE group_id=? AND user_id=?",
                      (group_id, user_id))
            if not c.fetchone():
                return f"❌ 用户 {user_name} 不是管理员"

            # 取消管理员
            c.execute("DELETE FROM t_admin WHERE group_id=? AND user_id=?",
                      (group_id, user_id))

            conn.commit()
            admin_list = self.get_admin_list(group_id)
            return f"✅ 已取消用户 {user_name} 的管理员权限\n\n{admin_list}"

        except Exception as e:
            logger.exception(f"[PKTracker] 取消管理员异常: {str(e)}")
            return "❌ 取消管理员失败,请稍后重试"
        finally:
            conn.close()

    def get_admin_list(self, group_id: str) -> str:
        """获取群内管理员列表
        Args:
            group_id: 群组ID
        Returns:
            str: 管理员列表信息
        """
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 获取所有管理员ID
            c.execute("""SELECT user_id FROM t_admin WHERE group_id=?""", (group_id,))
            admin_ids = [row[0] for row in c.fetchall()]

            # 获取超级管理员ID
            super_admin_ids = self.config.get("super_admins", [])

            # 合并所有管理员ID
            all_admin_ids = list(set(admin_ids + super_admin_ids))

            if not all_admin_ids:
                return "👥 当前群组暂无管理员"

            # 获取管理员昵称
            nickname_map = self.user_manager._get_nickname_by_user_ids(all_admin_ids)

            # 生成管理员列表消息
            message = "👥 管理员列表\n==================="

            # 先显示超级管理员
            for user_id in super_admin_ids:
                if user_id in nickname_map and nickname_map[user_id]:  # 添加昵称非空检查
                    message += f"\n\n👑 超级管理员: {nickname_map[user_id]}"

            # 显示普通管理员
            for user_id in admin_ids:
                if user_id not in super_admin_ids and user_id in nickname_map and nickname_map[user_id]:  # 添加昵称非空检查
                    message += f"\n\n⭐ 管理员: {nickname_map[user_id]}"

            return message

        except Exception as e:
            logger.exception(f"[PKTracker] 获取管理员列表异常: {str(e)}")
            return "❌ 获取管理员列表失败,请稍后重试"
        finally:
            conn.close()
