import schedule
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

scripts = ["test4.py", 
        #    "/code/畢專test/New_Summary/scripts/quick_run.py",
        #    "/code/畢專test/demo/data_to_supabase/generate_categories_from_single_news.py",
        #    "/code/畢專test/demo/data_to_supabase/generate_picture_to_supabase/generate_from_supabase.py",
        #    "Relative_News.py"
        ]

def run_scripts():
    """執行所有指定的 Python 腳本"""
    for script in scripts:
        logging.info(f"執行 {script} ...")
        result = subprocess.run(
            ["python", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        if result.returncode != 0:
            logging.error(f"{script} 執行出錯：\n{result.stderr}")
            break
        else:
            logging.info(f"{script} 輸出：\n{result.stdout}")


def main():
    """主函數"""
    # 立即執行一次
    logging.info("🟢 啟動，立即執行一次")
    run_scripts()

    # 設定排程（每 12 小時執行一次）
    schedule.every(12).hours.do(lambda: logging.info("🔁 排程觸發") or run_scripts())

    # 持續運行排程
    while True:
        schedule.run_pending()
        time.sleep(5)


if __name__ == "__main__":
    main()
