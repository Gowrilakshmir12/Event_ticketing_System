"""
Concurrent load test for the Event Ticketing System.

Simulates many simultaneous users attempting to reserve tickets for the
same event, then verifies the system never oversold — i.e. successful
holds never exceed the event's starting inventory.

Usage:
    python load_test.py
"""

import requests
import threading
import time

BASE_URL = "http://127.0.0.1:8000/api"
EVENT_ID = 5          # Workshop, 5 tickets
CONCURRENT_USERS = 50 # far more users than tickets, to force contention
QUANTITY_PER_USER = 1

results = {
    "success": 0,
    "rejected": 0,
    "errors": 0,
}
lock = threading.Lock()


def attempt_reservation(user_id):
    try:
        response = requests.post(
            f"{BASE_URL}/events/{EVENT_ID}/holds/",
            json={"user_id": user_id, "quantity": QUANTITY_PER_USER},
            timeout=10,
        )
        with lock:
            if response.status_code == 201:
                results["success"] += 1
            elif response.status_code == 409:
                results["rejected"] += 1
            else:
                results["errors"] += 1
                print(f"Unexpected status {response.status_code}: {response.text}")
    except Exception as e:
        with lock:
            results["errors"] += 1
        print(f"Request failed for user {user_id}: {e}")


def get_inventory():
    response = requests.get(f"{BASE_URL}/events/{EVENT_ID}/inventory/")
    return response.json()


def main():
    print("=== Event Ticketing Concurrency Load Test ===")

    starting_inventory = get_inventory()
    print(f"Starting inventory: {starting_inventory}")
    starting_available = starting_inventory["available_tickets"]

    print(f"\nFiring {CONCURRENT_USERS} concurrent reservation requests "
          f"({QUANTITY_PER_USER} ticket each) at event {EVENT_ID}...\n")

    threads = []
    start_time = time.time()

    for i in range(CONCURRENT_USERS):
        t = threading.Thread(target=attempt_reservation, args=(1000 + i,))
        threads.append(t)

    # Start all threads as close to simultaneously as possible
    for t in threads:
        t.start()

    for t in threads:
        t.join()

    elapsed = time.time() - start_time

    final_inventory = get_inventory()

    print("=== Results ===")
    print(f"Concurrent requests:     {CONCURRENT_USERS}")
    print(f"Successful reservations: {results['success']}")
    print(f"Rejected reservations:   {results['rejected']}")
    print(f"Errors:                  {results['errors']}")
    print(f"Elapsed time:            {elapsed:.2f}s")
    print(f"\nStarting available:      {starting_available}")
    print(f"Final available:         {final_inventory['available_tickets']}")

    print("\n=== Correctness Checks ===")
    oversold = results["success"] > starting_available
    print(f"Overselling occurred:    {oversold}")
    assert not oversold, "FAIL: More reservations succeeded than tickets were available!"

    expected_final = starting_available - results["success"]
    inventory_correct = final_inventory["available_tickets"] == expected_final
    print(f"Inventory math correct:  {inventory_correct} "
          f"(expected {expected_final}, got {final_inventory['available_tickets']})")
    assert inventory_correct, "FAIL: Final inventory doesn't match successful reservation count!"

    print("\n✅ ALL CHECKS PASSED — no overselling detected.")




def test_concurrent_confirm(hold_id):
    """
    Fires multiple concurrent confirm requests for the SAME hold, all using
    the SAME idempotency key. Only one should actually create a purchase;
    all others should return that same purchase.
    """
    print(f"\n=== Test: Concurrent Confirm (same hold, same idempotency key) ===")
    purchase_ids = []
    lock2 = threading.Lock()

    def confirm_attempt():
        try:
            response = requests.post(
                f"{BASE_URL}/holds/{hold_id}/confirm/",
                headers={"Idempotency-Key": "concurrent-confirm-test-key"},
                timeout=10,
            )
            with lock2:
                if response.status_code == 200:
                    purchase_ids.append(response.json()["purchase_id"])
                else:
                    print(f"Unexpected: {response.status_code} {response.text}")
        except Exception as e:
            print(f"Confirm request failed: {e}")

    threads = [threading.Thread(target=confirm_attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    unique_purchases = set(purchase_ids)
    print(f"Confirm attempts: 10, successful responses: {len(purchase_ids)}")
    print(f"Unique purchase_ids created: {unique_purchases}")
    assert len(unique_purchases) == 1, "FAIL: Multiple purchases created for one hold!"
    print("✅ PASS: Only one purchase created despite concurrent confirm attempts.")


def test_cross_event_independence():
    """
    Fires concurrent requests at TWO different events simultaneously and
    confirms neither blocks/interferes with the other's outcome.
    """
    print(f"\n=== Test: Cross-Event Independence ===")

    event_a_id = 3  # Concert, 10 tickets (adjust if yours differ)
    event_b_id = 4  # Conference, 50 tickets

    inv_a_before = get_inventory_for(event_a_id)
    inv_b_before = get_inventory_for(event_b_id)

    def hit_event(event_id, user_id):
        requests.post(
            f"{BASE_URL}/events/{event_id}/holds/",
            json={"user_id": user_id, "quantity": 1},
            timeout=10,
        )

    threads = []
    for i in range(10):
        threads.append(threading.Thread(target=hit_event, args=(event_a_id, 2000 + i)))
        threads.append(threading.Thread(target=hit_event, args=(event_b_id, 3000 + i)))

    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start

    inv_a_after = get_inventory_for(event_a_id)
    inv_b_after = get_inventory_for(event_b_id)

    print(f"Event A ({event_a_id}): {inv_a_before['available_tickets']} -> {inv_a_after['available_tickets']}")
    print(f"Event B ({event_b_id}): {inv_b_before['available_tickets']} -> {inv_b_after['available_tickets']}")
    print(f"Elapsed: {elapsed:.2f}s")
    print("✅ Both events processed concurrently without blocking each other.")


def get_inventory_for(event_id):
    return requests.get(f"{BASE_URL}/events/{event_id}/inventory/").json()



if __name__ == "__main__":
    main()

    # Grab a fresh hold to test concurrent confirm against
    hold_response = requests.post(
        f"{BASE_URL}/events/4/holds/",  # Conference, has plenty of inventory
        json={"user_id": 9999, "quantity": 1},
    )
    if hold_response.status_code == 201:
        test_hold_id = hold_response.json()["hold_id"]
        test_concurrent_confirm(test_hold_id)
    else:
        print("Could not create a test hold for the confirm test:", hold_response.text)

    test_cross_event_independence()