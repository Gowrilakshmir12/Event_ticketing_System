# Event Ticketing System with Overselling Prevention

## 1. Project Overview

The **Event Ticketing System** is a backend reservation service designed to handle high-demand events where a large number of users may attempt to reserve a limited number of tickets simultaneously.

The primary objective is to **prevent ticket overselling under concurrent requests** while ensuring that temporarily held tickets are automatically released when checkout is not completed.

The system supports multiple events, with each event maintaining its own independent ticket inventory and reservation state.

The system provides:

- Temporary ticket holds during checkout.
- Purchase confirmation before a hold expires.
- Automatic expiration and release of abandoned holds.
- FIFO waitlist when sufficient inventory is unavailable.
- Waitlist backfill when tickets are released.
- Concurrency-safe reservations using PostgreSQL.
- Concurrent load testing using a Python-based script.

The implementation focuses on the backend reservation and concurrency mechanisms. A frontend application and real payment integration are outside the scope of this implementation.

---

# 2. Features

### Multi-Event Inventory

Each event has its own ticket inventory. Operations for one event do not affect the inventory of another event.

### Temporary Ticket Holds

Users can temporarily reserve a specified number of tickets while completing checkout.

### Purchase Confirmation

A valid, non-expired hold can be confirmed and converted into a permanent purchase.

### Automatic Hold Expiration

If a user does not confirm a hold within the configured time period, the hold expires and its tickets are returned to the event's available inventory.

### Concurrency-Safe Reservation

PostgreSQL transactions and row-level locking ensure that concurrent reservation requests cannot oversell an event.

### Waitlist

Users can join a FIFO waitlist when sufficient tickets are unavailable.

### Waitlist Backfill

When tickets become available due to expired holds, the system can allocate them to eligible waitlisted users through new temporary holds.

### Concurrent Load Testing

A Python-based load-testing script simulates a large number of simultaneous reservation requests to verify the concurrency mechanism.

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

The system uses the following primary entities:

### Event

Stores information about each event.

```text
Event
----------------
id
name
description
event_date
```

### Inventory

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

### Hold

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
```

Possible hold states include:

```text
HELD
CONFIRMED
EXPIRED
```

### Purchase

Represents a permanently confirmed reservation.

```text
Purchase
----------------
id
hold_id
event_id
user_id
quantity
created_at
```

### Waitlist

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

### Example

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
Final available inventory:     0
```

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

A hold can only be confirmed if:

- It is still in the `HELD` state.
- It has not expired.
- It has not already been confirmed.

Example:

```http
POST /api/holds/15/confirm/
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

# 8. Hold Expiration

A temporary hold remains valid only for the configured hold duration.

If the user does not confirm the hold before expiration:

```text
HELD
  ↓
EXPIRED
  ↓
Inventory Released
  ↓
Waitlist Checked
```

The expiry process identifies expired holds and returns their ticket quantity to the corresponding event's available inventory.

The user does not need to call a separate expiration API.

If the user attempts to confirm an expired hold, the confirmation API rejects the request.

---

# 9. Setup and Installation

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

### Seed the Database

After running the database migrations, execute:

```bash
python manage.py seed_data

## Start the Development Server

```bash
python manage.py runserver
```

---

# 10. Testing

The project includes a Python-based concurrent load-testing script that sends multiple reservation requests simultaneously to the Django API.

### Example Test

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

The concurrency test should be repeated with different inventory sizes and request volumes to verify that the system consistently maintains correct inventory.

### Additional Test Scenarios

1. Reservation when sufficient inventory exists.
2. Reservation when inventory is insufficient.
3. Multiple concurrent requests for the last available ticket.
4. Successful hold confirmation.
5. Confirmation after hold expiration.
6. Duplicate hold confirmation.
7. Automatic release of expired holds.
8. Joining the waitlist when inventory is exhausted.
9. Allocation of released inventory to waitlisted users.
10. Concurrent reservations for different events.

---

# 11. Key Assumptions

- The system supports multiple events.
- Each event has an independent inventory record.
- Each ticket is represented as one unit of inventory.
- A temporary hold has a fixed expiration period.
- The waitlist follows FIFO ordering.
- Waitlist allocation considers the requested ticket quantity.
- PostgreSQL is the authoritative source of inventory and reservation state.
- Payment processing is simulated and no real payment gateway is integrated.
- Inventory displayed through the GET API is informational and may change immediately due to concurrent activity.
- Authentication and authorization are outside the current implementation scope.

---

# 12. Limitations and Scope

## In Scope

- Multiple event management.
- Event-specific inventory.
- Temporary ticket holds.
- Purchase confirmation.
- Automatic hold expiration.
- Inventory release after expiration.
- FIFO waitlist.
- Waitlist backfill.
- PostgreSQL-based concurrency control.
- Concurrent load testing.

## Out of Scope

The following features are intentionally excluded due to the **limited implementation timeline** and the need to focus on the core concurrency problem:

- Frontend application.
- Real payment gateway.
- User authentication and authorization.
- Email/SMS notifications.
- Redis caching.
- Celery or distributed task queues.
- Microservices architecture.
- Kubernetes/cloud deployment.
- Advanced seat selection.
- Dynamic pricing.

These limitations allow the implementation to focus on the primary requirement:

> **Preventing ticket overselling under genuine concurrent requests while correctly managing temporary holds, expired inventory, and waitlisted users.**

---

# 13. Success Criteria

The system is considered successful if it maintains inventory correctness under concurrent load.

For every event:

```text
Successful Reservations ≤ Available Inventory
```

The system must ensure that:

- No event is oversold.
- Expired holds release their tickets.
- Valid holds can be confirmed only once.
- Waitlisted users can be considered when inventory becomes available.
- Concurrent requests for different events do not unnecessarily block each other.
- The load-testing script demonstrates that the concurrency mechanism works correctly.
