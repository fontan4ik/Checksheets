import subprocess
import sys
import time
import threading
from datetime import datetime, time as dt_time, timedelta
import os


def run_script(script_name):
    """Запуск указанного скрипта"""
    try:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Запуск {script_name}...")
        result = subprocess.run([sys.executable, script_name],
                              capture_output=True,
                              text=True,
                              timeout=3600)  # таймаут 1 час на случай зависания

        if result.returncode == 0:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {script_name} успешно завершен")
            if result.stdout.strip():
                print(f"STDOUT: {result.stdout.strip()}")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ошибка при выполнении {script_name}")
            print(f"STDERR: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Время выполнения {script_name} истекло (таймаут)")
    except FileNotFoundError:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Файл не найден: {script_name}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Исключение при запуске {script_name}: {str(e)}")


def run_etm_sync():
    """Запуск скрипта etm_sync_local.py"""
    script_path = os.path.join(os.path.dirname(__file__), 'etm_sync_local.py')
    run_script(script_path)


def run_feron_sync():
    """Запуск скрипта feron_sync_local.py"""
    script_path = os.path.join(os.path.dirname(__file__), 'feron_sync_local.py')
    run_script(script_path)


def run_rs_sync():
    """Запуск скрипта rs_sync_local.py"""
    script_path = os.path.join(os.path.dirname(__file__), 'rs_sync_local.py')
    run_script(script_path)


def run_etm_and_feron():
    """Запуск ETM и Feron параллельно"""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Запуск ETM и Feron синхронизации")
    
    etm_thread = threading.Thread(target=run_etm_sync)
    feron_thread = threading.Thread(target=run_feron_sync)
    
    etm_thread.start()
    feron_thread.start()
    
    etm_thread.join()
    feron_thread.join()
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ETM и Feron синхронизация завершена\n")


def calculate_next_etm_feron_time():
    """Вычисляет время до следующего запуска ETM/Feron (00:00 или 09:00)"""
    now = datetime.now()
    today_midnight = datetime.combine(now.date(), dt_time(0, 0))
    today_9am = datetime.combine(now.date(), dt_time(9, 0))
    tomorrow_midnight = datetime.combine(now.date(), dt_time(0, 0)) + timedelta(days=1)
    
    if now < today_midnight:
        return (today_midnight - now).total_seconds()
    elif now < today_9am:
        return (today_9am - now).total_seconds()
    else:
        return (tomorrow_midnight - now).total_seconds()


def main(test_mode=False):
    """Основная функция планировщика с расписанием:
    - ETM и Feron: в 00:00 и 09:00
    - RS: каждые 3 часа
    """
    from datetime import timedelta
    
    if test_mode:
        print("ТЕСТОВЫЙ РЕЖИМ: выполнение одной итерации без ожидания")
        print(f"Текущее время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        run_etm_and_feron()
        run_rs_sync()
        return

    print("=" * 70)
    print("Планировщик синхронизации запущен")
    print("Расписание:")
    print("  - ETM и Feron: в 00:00 и 09:00")
    print("  - RS: каждые 3 часа")
    print(f"Текущее время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Для остановки скрипта используйте Ctrl+C")
    print("=" * 70)

    try:
        # Переменные для отслеживания последнего запуска
        last_etm_feron_run = None
        last_rs_run = None
        
        # Выполняем первый запуск сразу
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Первоначальный запуск всех скриптов")
        run_etm_and_feron()
        last_etm_feron_run = datetime.now()
        
        run_rs_sync()
        last_rs_run = datetime.now()

        while True:
            now = datetime.now()
            current_hour = now.hour
            current_minute = now.minute
            
            # Проверка времени для ETM и Feron (00:00 или 09:00)
            if (current_hour == 0 or current_hour == 9) and current_minute == 0:
                if last_etm_feron_run is None or (now - last_etm_feron_run).total_seconds() > 120:
                    run_etm_and_feron()
                    last_etm_feron_run = now
            
            # Проверка времени для RS (каждые 3 часа)
            if last_rs_run is None or (now - last_rs_run).total_seconds() >= 10800:  # 3 часа = 10800 секунд
                run_rs_sync()
                last_rs_run = now
            
            # Вычисляем время до следующих запусков
            next_rs_seconds = 10800 - (now - last_rs_run).total_seconds() if last_rs_run else 0
            
            # Вычисляем время до следующего ETM/Feron
            today_midnight = datetime.combine(now.date(), dt_time(0, 0))
            today_9am = datetime.combine(now.date(), dt_time(9, 0))
            tomorrow_midnight = today_midnight + timedelta(days=1)
            
            if now.hour < 9:
                next_etm_feron = today_9am
            else:
                next_etm_feron = tomorrow_midnight
            
            next_etm_feron_seconds = (next_etm_feron - now).total_seconds()
            
            # Выводим статус
            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Статус:")
            print(f"  Следующий запуск RS через: {int(next_rs_seconds//3600)}ч {int((next_rs_seconds%3600)//60)}м")
            print(f"  Следующий запуск ETM/Feron: {next_etm_feron.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Спим 60 секунд перед следующей проверкой
            time.sleep(60)

    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Работа скрипта остановлена пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Критическая ошибка: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Планировщик для запуска скриптов синхронизации')
    parser.add_argument('--test', action='store_true', help='Запустить в тестовом режиме (одна итерация)')
    args = parser.parse_args()

    if args.test:
        main(test_mode=True)
    else:
        main()
