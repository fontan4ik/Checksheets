import etm_sync_local
import rs_sync_local
import feron_sync_local
import time

def main():
    print("==========================================")
    print("MASTER STOCK SYNC PROCESS")
    print("==========================================")
    
    # 1. ETM Sync
    try:
        print("\n--- [1/3] ETM Sync ---")
        etm_sync_local.sync_etm()
    except Exception as e:
        print(f"ETM Sync failed: {e}")
    
    # 2. Feron Sync
    try:
        print("\n--- [2/3] Feron Sync ---")
        print("Note: Currently Feron API returns 401 with the provided key. Skipping error...")
        feron_sync_local.sync_feron()
    except Exception as e:
        print(f"Feron Sync failed: {e}")

    # 3. RS Sync
    try:
        print("\n--- [3/3] RS Sync ---")
        rs_sync_local.sync_rs()
    except Exception as e:
        print(f"RS Sync failed: {e}")
        
    print("\n==========================================")
    print("All sync processes finished.")
    print("==========================================")

if __name__ == "__main__":
    main()
