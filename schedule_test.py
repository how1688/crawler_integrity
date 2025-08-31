import schedule
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

scripts = [
    "test5_play.py", 
    "./New_Summary/scripts/quick_run.py",
    "./demo/data_to_supabase/generate_categories_from_single_news.py",
    "./demo/data_to_supabase/generate_picture_to_supabase/generate_from_supabase.py",
    "./Relative_News.py"
]

def run_scripts():
    """執行所有指定的 Python 腳本"""
    for script in scripts:
        logging.info(f"▶ 執行 {script} ...")

        # 用 Popen 逐行讀取輸出
        process = subprocess.Popen(
            ["python", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        # 即時輸出進度
        for line in process.stdout:
            logging.info(f"[{script}] {line.strip()}")

        process.wait()  # 等待程式結束

        if process.returncode != 0:
            logging.error(f"❌ {script} 執行出錯 (return code {process.returncode})")
            break
        else:
            logging.info(f"✅ {script} 執行完成")

def main():
    """主函數"""
    logging.info("🟢 啟動，立即執行一次")
    run_scripts()

    # 每 12 小時排程
    schedule.every(12).hours.do(lambda: logging.info("🔁 排程觸發") or run_scripts())

    while True:
        schedule.run_pending()
        time.sleep(5)

if __name__ == "__main__":
    main()

