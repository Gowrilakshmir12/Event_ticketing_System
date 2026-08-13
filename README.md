# Event Ticketing System with Overselling Prevention

## 1. Project Overview

The **Event Ticketing System** is a backend reservation service designed to handle high-demand events where a large number of users may attempt to reserve a limited number of tickets simultaneously.

The primary objective is to **prevent ticket overselling under concurrent requests** while ensuring that temporarily held tickets are automatically released when checkout is not completed.

The system supports multiple events, with each event maintaining its own independent ticket inventory and reservation state.

The implementation focuses on the backend reservation and concurrency mechanisms. A frontend application and real payment integration are outside the scope of this implementation.

The system provides:

- Temporary ticket holds during checkout.
- Purchase confirmation before a hold expires.
- Automatic expiration and recovery of abandoned holds.
- FIFO-based waitlist management.
- Waitlist backfill when inventory becomes available.
- All-or-nothing ticket allocation.
- Idempotent purchase confirmation.
- Concurrency-safe reservations using PostgreSQL.
- Concurrent load testing using a Python-based script.

The main inventory invariant is:

```text
SOLD + ACTIVE HELD <= EVENT CAPACITY
```

This invariant must remain true even when many users attempt to reserve tickets simultaneously.

---

# 2. Features

## Multi-Event Inventory

Each event has its own independent ticket inventory. Operations for one event do not affect the inventory of another event.

This allows reservations for different events to proceed concurrently while requests competing for the same event are synchronized at the inventory level.

## Temporary Ticket Holds

Users can temporarily reserve a specified number of tickets while completing checkout.

A hold removes the requested quantity from the event's available inventory for a limited period.

A request for `N` tickets is accepted only when the complete quantity is available:

```text
available_tickets >= requested_quantity
```

Partial allocation is not performed during normal ticket reservation.

For example:

```text
Available = 2
Requested = 3

Result:
Reservation rejected
```

rather than:

```text
Allocate 2
Leave 1 pending
```

This keeps group bookings together.

## Purchase Confirmation

A valid, non-expired hold can be confirmed and converted into a permanent purchase.

Purchase confirmation is performed inside a database transaction so that hold confirmation, ticket state changes, and purchase creation happen atomically.

## Automatic Hold Expiration

If a user does not confirm a hold within the configured time period, the hold expires and its tickets are returned to the event's available inventory.

The expiry process is implemented as a background/scheduled process that periodically searches for expired active holds.

## Expiry Failure Recovery

The expiry operation is transactional and idempotent.

If the expiry worker fails before committing its transaction, the database rolls back the partial changes and the hold remains eligible for the next expiry cycle.

If the transaction commits successfully but the worker fails afterward, the database already contains the correct inventory and hold state. A later reconciliation/backfill process can safely continue any non-database side effects.

## Concurrency-Safe Reservation

PostgreSQL transactions and row-level locking ensure that concurrent reservation requests cannot oversell an event.

The event-specific inventory row is locked rather than the entire inventory table, allowing requests for unrelated events to continue independently.

## Duplicate-Safe Purchase Confirmation

Purchase confirmation uses an idempotency key to prevent retries from creating duplicate purchases.

Repeated requests using the same idempotency key return the existing confirmation result instead of creating another purchase.

## Waitlist

Users can join a FIFO waitlist when sufficient inventory is unavailable.

Waitlist entries contain the quantity requested by the user.

## Waitlist Backfill

When tickets become available because of hold expiry or another inventory release, the system attempts to satisfy eligible waitlist requests.

The system uses **all-or-nothing fulfillment**:

> If a user requests `N` tickets, the waitlist allocates either all `N` tickets or none.

This avoids partially satisfying a group request.

If the first waitlist user cannot currently be fully satisfied, the system may temporarily skip that entry and evaluate later entries that can be fulfilled completely. This prevents available inventory from being unnecessarily left unused.

## Concurrent Load Testing

A Python-based load-testing script simulates a large number of simultaneous reservation and confirmation requests to verify the concurrency mechanism.

---

# 3. Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python |
| Backend Framework | Django |
| REST API | Django REST Framework |
| Database | PostgreSQL |
| Concurrency Control | PostgreSQL Transactions + Row-Level Locking |
| Load Testing | Python |

---

# 4. System Architecture

```text
                     ┌──────────────────────┐
                     │   Python Load Tester │
                     │  Concurrent Requests │
                     └──────────┬───────────┘
                                │
                                │ HTTP
                                ▼
                     ┌──────────────────────┐
                     │     Django + DRF     │
                     │       REST API       │
                     └──────────┬───────────┘
                                │
                                │ Database Operations
                                ▼
                     ┌──────────────────────┐
                     │      PostgreSQL      │
                     │                      │
                     │ Event                │
                     │ Inventory            │
                     │ Hold                 │
                     │ Purchase             │
                     │ Waitlist             │
                     └──────────▲───────────┘
                                │
                                │ Expired Hold Processing
                                │
                     ┌──────────┴───────────┐
                     │    Expiry Process    │
                     └──────────────────────┘
```

PostgreSQL acts as the authoritative source of truth for event inventory and reservation state.

Each event has independent inventory, allowing concurrent users to reserve tickets for different events without unnecessarily blocking one another.

---

# 5. Database Design

The system uses the following primary entities.

## Event

Stores information about each event.

```text
Event
----------------
id
name
description
event_date
```

## Inventory

Maintains ticket availability for each event.

```text
Inventory
----------------
id
event_id
total_tickets
available_tickets
```

Each event has its own inventory record.

## Hold

Represents a temporary ticket reservation.

```text
Hold
----------------
id
event_id
user_id
quantity
status
expires_at
created_at
idempotency_key
```

Possible hold states include:

```text
HELD
CONFIRMED
EXPIRED
```

## Purchase

Represents a permanently confirmed reservation.

```text
Purchase
----------------
id
hold_id
event_id
user_id
quantity
idempotency_key
created_at
```

The idempotency key is unique so that the same confirmation request cannot create multiple purchases.

## Waitlist

Stores users waiting for tickets to become available.

```text
Waitlist
----------------
id
event_id
user_id
quantity
status
created_at
```

Possible logical states include:

```text
WAITING
FULFILLED
```

---

# 6. Concurrency and Overselling Prevention

The most important part of the system is the reservation operation.

When a user requests tickets, the corresponding event's inventory row is locked using PostgreSQL row-level locking through Django's `select_for_update()`.

```text
BEGIN TRANSACTION
        ↓
Lock Inventory Row for Event
        ↓
Check Available Tickets
        ↓
If sufficient inventory
        ↓
Decrease Available Inventory
        ↓
Create Temporary Hold
        ↓
COMMIT
```

The lock is applied to the **specific event's inventory row**, not the entire inventory table.

For example:

```text
Event 1 Inventory → Locked
Event 2 Inventory → Available
Event 3 Inventory → Available
```

Therefore, concurrent requests for Event 1 are serialized while requests for other events can continue normally.

## Example

If Event 1 has:

```text
Available tickets = 10
```

and 1,000 users simultaneously request one ticket:

```text
Concurrent requests:        1000
Successful reservations:      10
Rejected reservations:       990
Overselling:                   0
Final available inventory:    0
```

The exact number of successful reservations depends on the inventory available at the start of the test, but it must never exceed the event capacity.

---

# 7. API Details

## 7.1 Get Event Inventory

```http
GET /api/events/{event_id}/inventory/
```

Returns the current inventory for a specific event.

Example:

```http
GET /api/events/1/inventory/
```

Response:

```json
{
    "event_id": 1,
    "total_tickets": 100,
    "available_tickets": 37
}
```

The returned inventory count is informational. The reservation API performs the authoritative availability check under a database lock.

---

## 7.2 Create Temporary Hold

```http
POST /api/events/{event_id}/holds/
```

Temporarily reserves tickets for a user.

Example:

```http
POST /api/events/1/holds/
```

Request:

```json
{
    "user_id": 101,
    "quantity": 2
}
```

Example response:

```json
{
    "hold_id": 15,
    "event_id": 1,
    "user_id": 101,
    "quantity": 2,
    "status": "HELD",
    "expires_at": "2026-08-11T17:30:00Z"
}
```

The requested tickets are removed from the event's available inventory until the hold is confirmed or expires.

---

## 7.3 Confirm Hold

```http
POST /api/holds/{hold_id}/confirm/
```

Confirms a valid temporary hold and converts it into a permanent purchase.

The request should include a unique idempotency key, for example:

```http
Idempotency-Key: 8d7f2a91-xxxx-xxxx
```

A hold can only be confirmed if:

- It is still in the `HELD` state.
- It has not expired.
- It has not already been confirmed.
- The tickets still belong to the hold.

Example:

```http
POST /api/holds/15/confirm/
Idempotency-Key: ABC123
```

Response:

```json
{
    "hold_id": 15,
    "purchase_id": 42,
    "status": "CONFIRMED"
}
```

If the hold has expired, the confirmation request is rejected.

---

## 7.4 Join Waitlist

```http
POST /api/events/{event_id}/waitlist/
```

Adds a user to the event's FIFO waitlist when sufficient tickets are unavailable.

Example:

```http
POST /api/events/1/waitlist/
```

Request:

```json
{
    "user_id": 205,
    "quantity": 2
}
```

Response:

```json
{
    "waitlist_id": 7,
    "event_id": 1,
    "status": "WAITING"
}
```

The waitlist is maintained independently for each event.

---

# 8. Hold Expiration and Failure Recovery

A temporary hold remains valid only for the configured hold duration.

For example:

```text
Hold Duration = 5 minutes
```

If the user does not confirm the hold within that period:

```text
HELD
  ↓
EXPIRED
  ↓
Inventory Released
  ↓
Waitlist Checked
```

## Expiry Processing

A background or scheduled expiry process periodically searches for active holds whose expiration time has passed.

Conceptually:

```sql
SELECT *
FROM holds
WHERE status = 'HELD'
AND expires_at <= CURRENT_TIMESTAMP;
```

For each expired hold, the system performs the release operation inside a transaction.

```text
Find expired hold
        ↓
BEGIN TRANSACTION
        ↓
Lock / verify hold
        ↓
Check hold is still HELD
        ↓
Release ticket quantity
        ↓
Mark hold EXPIRED
        ↓
COMMIT
        ↓
Trigger waitlist backfill
```

The important point is that **inventory release and hold-state update occur in the same transaction**.

### Failure Before Commit

Suppose the worker begins processing:

```text
BEGIN TRANSACTION
        ↓
Release inventory
        ↓
Worker crashes
```

Because the transaction was not committed:

```text
Database rollback
        ↓
Inventory release is undone
        ↓
Hold remains HELD
```

The next expiry cycle can detect the same expired hold and retry it.

### Failure After Commit

Suppose:

```text
Release inventory
        ↓
Mark hold EXPIRED
        ↓
COMMIT
        ↓
Worker crashes before backfill/notification
```

The database already contains the correct state:

```text
Hold = EXPIRED
Inventory = RELEASED
```

The next recovery/reconciliation cycle can detect the newly available inventory and retry the waitlist backfill.

This separates the authoritative database state from non-critical follow-up actions.

### Idempotent Expiry

The expiry operation checks that the hold is still in the `HELD` state before changing it.

Therefore:

```text
First expiry attempt:
HELD → EXPIRED
tickets released

Second expiry attempt:
EXPIRED → no operation
```

This prevents duplicate inventory release.

The process also verifies that the tickets being released are still associated with the same hold so that an old expiry operation cannot accidentally release tickets that have already been reallocated.

---

# 9. Purchase Confirmation Transaction and Duplicate Prevention

Purchase confirmation is handled as an atomic transaction.

```text
Client
   |
   v
POST /api/holds/{hold_id}/confirm/
   |
   v
Validate request + idempotency key
   |
   v
BEGIN TRANSACTION
   |
   v
Lock relevant hold/inventory state
   |
   v
Check hold status
   |
   v
Check hold expiration
   |
   v
Check idempotency key
   |
   v
Create Purchase
   |
   v
Change HELD -> SOLD
   |
   v
Change Hold -> CONFIRMED
   |
   v
COMMIT
   |
   v
Return confirmation
```

All state changes must succeed or all must be rolled back.

## First Confirmation

```text
Request:
Idempotency-Key = ABC123

No previous purchase found
        ↓
Create Purchase
        ↓
HELD -> SOLD
        ↓
HELD -> CONFIRMED
        ↓
COMMIT
```

## Duplicate Confirmation

If the client retries the same request:

```text
Request:
Idempotency-Key = ABC123

Existing confirmation found
        ↓
Do not create another Purchase
        ↓
Do not decrement inventory again
        ↓
Return existing purchase result
```

The database should enforce:

```text
UNIQUE(idempotency_key)
```

This provides a second layer of protection if two identical confirmation requests arrive concurrently.

## Concurrent Confirmation

Two requests can arrive at almost exactly the same time:

```text
Request A                    Request B
    |                            |
    |---- acquire lock ----------|
    |                            | waits
    |
    | Create purchase
    | HELD -> SOLD
    | CONFIRMED
    | COMMIT
    |
    |                      acquire lock
    |                            |
    |                      Check state
    |                            |
    |                      Already CONFIRMED
    |                            |
    |                      Return existing result
```

Thus, only one purchase is created.

---

# 10. Waitlist and Backfill Logic

When a requested quantity is unavailable, a user may join the waitlist.

The system follows:

> **All-or-nothing waitlist fulfillment.**

If a user requests 3 tickets, the system allocates:

```text
3 tickets → YES
2 tickets → NO
1 ticket  → NO
```

This is intentional because the current project treats the requested quantity as a group requirement.

## Full Availability

Suppose:

```text
Available = 5

Waitlist:
A → 3
B → 2
```

Backfill:

```text
A requests 3
3 <= 5
    ↓
A receives 3
Available = 2

B requests 2
2 <= 2
    ↓
B receives 2
Available = 0
```

Both entries are fully satisfied.

---

# 11. Partial Ticket Availability in the Waitlist

The system does **not** automatically partially allocate tickets to a waitlisted user.

Suppose:

```text
Available = 2

Waitlist:
A → 3
B → 2
C → 1
```

The first user requests 3 but only 2 are available.

The system therefore does not give A two tickets.

Instead:

```text
A → 3 requested, 2 available
       ↓
Cannot fully satisfy
       ↓
Remain WAITING
```

The system can then evaluate the next waitlist entry:

```text
B → requests 2
2 available
       ↓
Allocate all 2
       ↓
Available = 0
```

User A remains on the waitlist and can be reconsidered when at least 3 tickets become available.

## Why Partial Allocation Is Not Used

Partial allocation can be undesirable for group bookings because the user requested a specific number of tickets.

For example:

```text
Requested = 4
Available = 2
```

Automatically giving 2 tickets may leave the user unable to attend with the intended group.

Therefore, the current design uses all-or-nothing allocation.

A future enhancement could introduce an explicit user-controlled partial-allocation offer, but that is outside the core implementation.

---

# 12. Waitlist Processing Policy

The waitlist follows FIFO ordering, but an unfulfillable request does not permanently block all later requests.

Example:

```text
Available = 3

Waitlist:
A → 4 tickets
B → 2 tickets
C → 1 ticket
```

Processing:

```text
A → 4 > 3 → skip temporarily

B → 2 <= 3
    allocate 2
    remaining = 1

C → 1 <= 1
    allocate 1
    remaining = 0
```

Result:

```text
A → remains WAITING
B → fulfilled
C → fulfilled
Available → 0
```

This provides two desirable properties:

1. A user is never forced to accept fewer tickets than requested.
2. Available tickets are not unnecessarily left unused.

User A is reconsidered during later backfill operations when sufficient inventory becomes available.

---

# 13. Waitlist Backfill Transaction

Waitlist allocation must also be protected against concurrent workers.

The backfill operation follows:

```text
Tickets become available
        ↓
BEGIN TRANSACTION
        ↓
Lock Event Inventory
        ↓
Read current available quantity
        ↓
Find eligible waitlist entry
        ↓
Check requested quantity <= available quantity
        ↓
Create temporary hold
        ↓
Decrease available inventory
        ↓
Update waitlist status
        ↓
COMMIT
```

If multiple workers attempt to process the same event:

```text
Worker A ───────┐
                ├──> Event Inventory
Worker B ───────┘
```

only one worker can modify the locked inventory row at a time.

After the first worker commits, the second worker rechecks the latest inventory state before allocating anything.

This prevents the same available tickets from being assigned to multiple waitlist users.

---

# 14. Waitlist-to-Hold Flow

Waitlist backfill does not immediately mark tickets as sold.

Instead:

```text
WAITING
   ↓
Eligible request found
   ↓
Create HELD reservation
   ↓
Notify / expose opportunity to user
   ↓
Normal purchase confirmation
   ↓
SOLD
```

The waitlist-generated hold follows the same expiry rules as a normal hold.

If the user does not confirm before expiry:

```text
HELD
  ↓
EXPIRED
  ↓
Inventory Released
  ↓
Waitlist Backfill
```

This allows waitlist allocation to reuse the existing hold and confirmation mechanisms rather than introducing a separate purchase flow.

---

# 15. API and State Interaction

The main state transitions are:

```text
                ┌─────────────────────┐
                │      AVAILABLE      │
                └──────────┬──────────┘
                           │
                     Create Hold
                           │
                           v
                ┌─────────────────────┐
                │        HELD         │
                └──────┬───────┬──────┘
                       │       │
              Confirm  │       │ Expire
                       │       │
                       v       v
                ┌─────────┐ ┌─────────┐
                │  SOLD   │ │EXPIRED  │
                └─────────┘ └────┬────┘
                                 │
                                 v
                           AVAILABLE
                                 │
                          Waitlist match
                                 │
                                 v
                               HELD
```

The same state machine is used whether tickets are obtained directly or through waitlist backfill.

---

# 16. Setup and Installation

## Prerequisites

The following software is required:

- Python
- PostgreSQL
- pip
- Git

## Clone the Repository

```bash
git clone <repository-url>
cd <project-directory>
```

## Create a Virtual Environment

```bash
python -m venv venv
```

### Windows

```bash
venv\Scripts\activate
```

### Linux/macOS

```bash
source venv/bin/activate
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Configure PostgreSQL

Create a PostgreSQL database and configure the database connection using the project's environment/configuration settings.

Example:

```text
DATABASE_NAME=<database_name>
DATABASE_USER=<database_user>
DATABASE_PASSWORD=<database_password>
DATABASE_HOST=localhost
DATABASE_PORT=5432
```

## Apply Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

## Database Seeding

The project provides a custom Django management command to populate the database with sample data for development and testing.

```bash
python manage.py seed_data
```

## Start the Development Server

```bash
python manage.py runserver
```

---

# 17. Testing

The project includes a Python-based concurrent load-testing script that sends multiple reservation requests simultaneously to the Django API.

## Basic Concurrency Test

Suppose Event 1 has:

```text
Initial inventory:       10
Concurrent users:      1000
Tickets requested/user:   1
```

Expected result:

```text
Successful reservations: 10
Rejected reservations:  990
Overselling:              0
Final inventory:           0
```

The exact request outcomes may vary based on scheduling, but the number of successful reservations must never exceed available capacity.

## Additional Test Scenarios

1. Reservation when sufficient inventory exists.
2. Reservation when inventory is insufficient.
3. Multiple concurrent requests for the last available ticket.
4. Successful hold confirmation.
5. Confirmation after hold expiration.
6. Duplicate hold confirmation using the same idempotency key.
7. Concurrent confirmation requests for the same hold.
8. Automatic release of expired holds.
9. Repeated expiry processing.
10. Expiry worker failure and subsequent recovery.
11. Joining the waitlist when inventory is exhausted.
12. Full waitlist fulfillment.
13. Partial inventory where the first waitlist request cannot be completely fulfilled.
14. Skipping an unfulfillable waitlist request.
15. Backfill of released inventory.
16. Concurrent waitlist backfill.
17. Concurrent reservations for different events.

## Correctness Conditions

Load testing should verify:

```text
SOLD <= EVENT CAPACITY
```

and:

```text
No duplicate purchase
No duplicate ticket allocation
No negative inventory
No overselling
Expired holds eventually release inventory
Waitlist allocation never exceeds available inventory
```

---

# 18. Key Assumptions

- The system supports multiple events.
- Each event has an independent inventory record.
- Each ticket is represented as one unit of inventory.
- Seat-level selection and seat adjacency are outside the current scope.
- A temporary hold has a fixed expiration period.
- A user requesting `N` tickets expects the complete quantity.
- Partial allocation is not automatically performed.
- The waitlist follows FIFO ordering.
- An unfulfillable waitlist request may be skipped temporarily so later fulfillable requests can use available inventory.
- Waitlist allocation creates a temporary hold rather than immediately marking tickets as sold.
- PostgreSQL is the authoritative source of inventory and reservation state.
- Payment processing is simulated and no real payment gateway is integrated.
- Inventory displayed through the GET API is informational and may change immediately due to concurrent activity.
- Authentication and authorization are outside the current implementation scope.

---

# 19. Limitations and Scope

## In Scope

- Multiple event management.
- Event-specific inventory.
- Temporary ticket holds.
- Purchase confirmation.
- Duplicate confirmation prevention.
- Automatic hold expiration.
- Failure recovery for expired holds.
- Inventory release after expiration.
- FIFO waitlist.
- All-or-nothing waitlist fulfillment.
- Waitlist backfill.
- PostgreSQL-based concurrency control.
- Concurrent load testing.

## Out of Scope

The following features are intentionally excluded so that the implementation can focus on the core concurrency problem:

- Frontend application.
- Real payment gateway.
- User authentication and authorization.
- Email/SMS notifications.
- Redis caching.
- Celery or distributed task queues.
- Microservices architecture.
- Kubernetes/cloud deployment.
- Advanced seat selection.
- Seat adjacency.
- Dynamic pricing.

These limitations allow the implementation to focus on the primary requirement:

> **Preventing ticket overselling under genuine concurrent requests while correctly managing temporary holds, expired inventory, duplicate purchase confirmations, and waitlisted users.**

---

# 20. Future Enhancements

Possible future improvements include:

- Seat-level inventory management.
- Seat adjacency validation.
- Explicit user-controlled partial-allocation offers.
- Real payment gateway integration.
- Email/SMS notifications.
- Advanced waitlist priority rules.
- Redis-based distributed coordination.
- Distributed locking for multi-instance deployments.
- Monitoring and alerting.
- Automated inventory reconciliation.
- Real-time availability updates.
- Cloud deployment.

---

# 21. Success Criteria

The system is considered successful if it maintains inventory correctness under concurrent load.

For every event:

```text
Successful Ticket Allocations <= Event Capacity
```

The system must ensure that:

- No event is oversold.
- No ticket quantity is allocated twice.
- Expired holds release their inventory.
- Failed expiry processing can be retried safely.
- Valid holds can be confirmed only once.
- Duplicate confirmation requests do not create duplicate purchases.
- Waitlisted users can be considered when inventory becomes available.
- Partial waitlist fulfillment is not performed automatically.
- Unfulfillable waitlist requests do not unnecessarily prevent later fulfillable requests.
- Concurrent requests for different events do not unnecessarily block each other.
- The load-testing script demonstrates that the concurrency mechanism works correctly.
