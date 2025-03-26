import sqlite3

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
    
        # 修改任务表,添加 max_checkins 字段
        c.execute('''CREATE TABLE IF NOT EXISTS t_task
                       (task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id TEXT NOT NULL,
                        task_name TEXT NOT NULL,
                        frequency TEXT CHECK(frequency IN ('day','week','month')),
                        max_checkins INTEGER DEFAULT 1,
                        base_score INTEGER DEFAULT 1,
                        first_checkin_reward_enabled INTEGER DEFAULT 1,
                        first_checkin_reward INTEGER DEFAULT 3,
                        week_checkin_reward_enabled INTEGER DEFAULT 1,
                        week_checkin_reward INTEGER DEFAULT 3,
                        month_checkin_reward_enabled INTEGER DEFAULT 1,
                        month_checkin_reward INTEGER DEFAULT 5,
                        consecutive_checkin_reward_enabled INTEGER DEFAULT 1,
                        consecutive_checkin_reward INTEGER DEFAULT 3,
                        reminder_time TEXT,
                        remind_text TEXT,
                        enable INTEGER DEFAULT 1,
                        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        update_time DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
        # 创建打卡记录表
        c.execute('''CREATE TABLE IF NOT EXISTS t_checkin_log
                       (checkin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id INTEGER,
                        user_id TEXT NOT NULL,
                        checkin_time DATETIME NOT NULL,
                        content TEXT,
                        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        update_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES t_task(task_id))''')
    
        # 创建管理员表
        c.execute('''CREATE TABLE IF NOT EXISTS t_admin
                       (group_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        update_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(group_id, user_id))''')
    
        # 创建积分表
        c.execute('''CREATE TABLE IF NOT EXISTS t_bonus
                       (bonus_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id INTEGER NOT NULL,
                        user_id TEXT NOT NULL,
                        checkin_id INTEGER NOT NULL,
                        bonus_type TEXT CHECK(bonus_type IN ('base','first','consecutive','week','month')),
                        bonus_value INTEGER NOT NULL,
                        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        update_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES t_task(task_id),
                        FOREIGN KEY(checkin_id) REFERENCES t_checkin_log(checkin_id))''')
    
        # 创建触发器,用于自动更新update_time
        c.execute('''CREATE TRIGGER IF NOT EXISTS tg_task_update 
                   AFTER UPDATE ON t_task
                   BEGIN
                       UPDATE t_task SET update_time = CURRENT_TIMESTAMP
                       WHERE task_id = NEW.task_id;
                   END;''')
    
        c.execute('''CREATE TRIGGER IF NOT EXISTS tg_checkin_log_update 
                   AFTER UPDATE ON t_checkin_log
                   BEGIN
                       UPDATE t_checkin_log SET update_time = CURRENT_TIMESTAMP
                       WHERE checkin_id = NEW.checkin_id;
                   END;''')
    
        c.execute('''CREATE TRIGGER IF NOT EXISTS tg_admin_update 
                   AFTER UPDATE ON t_admin
                   BEGIN
                       UPDATE t_admin SET update_time = CURRENT_TIMESTAMP
                       WHERE group_id = NEW.group_id AND user_id = NEW.user_id;
                   END;''')
    
        c.execute('''CREATE TRIGGER IF NOT EXISTS tg_bonus_update 
                   AFTER UPDATE ON t_bonus
                   BEGIN
                       UPDATE t_bonus SET update_time = CURRENT_TIMESTAMP
                       WHERE bonus_id = NEW.bonus_id;
                   END;''')
    
        conn.commit()
        conn.close()