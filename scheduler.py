import subprocess
import sys
import time
import threading
from datetime import datetime
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

def run_rs_sync():
    """Запуск скрипта rs_sync_local.py"""
    script_path = os.path.join(os.path.dirname(__file__), 'rs_sync_local.py')
    run_script(script_path)

def schedule_scripts():
    """Запуск обоих скриптов параллельно"""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Начало выполнения задач по расписанию")

    # Создаем потоки для параллельного выполнения
    etm_thread = threading.Thread(target=run_etm_sync)
    rs_thread = threading.Thread(target=run_rs_sync)

    # Запускаем оба потока
    etm_thread.start()
    rs_thread.start()

    # Ждем завершения обоих потоков
    etm_thread.join()
    rs_thread.join()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Все задачи завершены\n")


def main(test_mode=False):

    """Основная функция - запуск по расписанию каждые 2 часа"""

    if test_mode:
        print("ТЕСТОВЫЙ РЕЖИМ: выполнение одной итерации без ожидания")
        print(f"Текущее время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        schedule_scripts()
        return

    print("Скрипт планировщика запущен. Будет выполнять задачи каждые 2 часа.")
    print(f"Текущее время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Для остановки скрипта используйте Ctrl+C")



    try:

        # Выполняем первый запуск сразу

        schedule_scripts()



        # Затем засыпаем на 2 часа и повторяем

        while True:

            # Конвертируем 2 часа в секунды (2 * 60 * 60 = 7200)

            sleep_time = 7200  # 2 часа в секундах



            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ожидание {sleep_time//3600} часов до следующего запуска...")



            # Разбиваем сон на интервалы по 60 секунд для возможности прерывания

            total_sleep = 0

            while total_sleep < sleep_time:

                time.sleep(60)

                total_sleep += 60

                if total_sleep % 3600 == 0:  # Каждый час выводим статус

                    remaining = sleep_time - total_sleep

                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Осталось времени до следующего запуска: {remaining//3600} часов {remaining%3600//60} минут")



            schedule_scripts()



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
