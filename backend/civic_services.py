import json
import hashlib
import math
import re
import sqlite3
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "an", "and", "are", "at", "be", "been", "by", "for", "from",
    "has", "have", "in", "is", "it", "near", "of", "on", "or", "the",
    "to", "was", "were", "with",
}
MIN_EXAMPLES_PER_CATEGORY = 5
MAX_STRATIFIED_FOLDS = 5


def tokens(text):
    return [
        word for word in TOKEN_PATTERN.findall((text or "").lower())
        if word not in STOP_WORDS and len(word) > 1
    ]


def tfidf_vectors(texts):
    token_lists = [tokens(text) for text in texts]
    document_frequency = Counter(
        word for words in token_lists for word in set(words)
    )
    count = len(token_lists)
    vocabulary = sorted(document_frequency)
    idf = {
        word: math.log((1 + count) / (1 + document_frequency[word])) + 1
        for word in vocabulary
    }
    vectors = []
    for words in token_lists:
        counts = Counter(words)
        vector = {
            word: (1 + math.log(frequency)) * idf[word]
            for word, frequency in counts.items()
        }
        magnitude = math.sqrt(sum(value * value for value in vector.values()))
        vectors.append({
            word: value / magnitude for word, value in vector.items()
        } if magnitude else {})
    return vocabulary, idf, vectors


def fit_tfidf_classifier(training_rows, version=1):
    usable = [
        (row["description"], row["category"])
        for row in training_rows
        if row["description"] and row["category"]
    ]
    labels = sorted({category for _, category in usable})
    vocabulary, idf, vectors = tfidf_vectors([text for text, _ in usable])
    word_index = {word: index for index, word in enumerate(vocabulary)}
    category_index = {category: index for index, category in enumerate(labels)}
    feature_count = len(vocabulary)
    weights = [[0.0] * feature_count for _ in labels]
    biases = [0.0] * len(labels)
    learning_rate = 0.15
    for _ in range(120):
        weight_gradient = [[0.0] * feature_count for _ in labels]
        bias_gradient = [0.0] * len(labels)
        for vector, (_, category) in zip(vectors, usable):
            scores = [
                biases[label]
                + sum(weights[label][word_index[word]] * value for word, value in vector.items())
                for label in range(len(labels))
            ]
            maximum = max(scores)
            exponentials = [math.exp(score - maximum) for score in scores]
            denominator = sum(exponentials)
            probabilities = [value / denominator for value in exponentials]
            expected = category_index[category]
            for label, probability in enumerate(probabilities):
                error = probability - (1 if label == expected else 0)
                bias_gradient[label] += error
                for word, value in vector.items():
                    weight_gradient[label][word_index[word]] += error * value
        for label in range(len(labels)):
            biases[label] -= learning_rate * bias_gradient[label] / len(usable)
            for feature in range(feature_count):
                weights[label][feature] -= learning_rate * (
                    weight_gradient[label][feature] / len(usable)
                    + 0.001 * weights[label][feature]
                )
    return {
        "model": "tfidf-logistic-regression",
        "version": version,
        "labels": labels,
        "vocabulary": vocabulary,
        "idf": idf,
        "weights": weights,
        "biases": biases,
        "sample_count": len(usable),
    }


def predict_with_tfidf_model(description, model, confidence_threshold=0.55):
    labels = model["labels"]
    vocabulary = model["vocabulary"]
    idf = model["idf"]
    word_index = {word: index for index, word in enumerate(vocabulary)}
    if not tokens(description):
        return {
            "category": None,
            "confidence": None,
            "model": model["model"],
            "model_version": model["version"],
            "trained": True,
            "needs_review": True,
        }
    input_counts = Counter(tokens(description))
    input_magnitude = math.sqrt(sum(
        ((1 + math.log(count)) * idf[word]) ** 2
        for word, count in input_counts.items() if word in idf
    ))
    if not input_magnitude:
        return {
            "category": None,
            "confidence": None,
            "model": model["model"],
            "model_version": model["version"],
            "trained": True,
            "needs_review": True,
        }
    input_vector = {
        word: ((1 + math.log(count)) * idf[word]) / input_magnitude
        for word, count in input_counts.items() if word in word_index
    }
    scores = [
        model["biases"][label]
        + sum(model["weights"][label][word_index[word]] * value for word, value in input_vector.items())
        for label in range(len(labels))
    ]
    maximum = max(scores)
    exponentials = [math.exp(score - maximum) for score in scores]
    denominator = sum(exponentials)
    probabilities = [value / denominator for value in exponentials]
    best = max(range(len(labels)), key=probabilities.__getitem__)
    confidence = probabilities[best]
    return {
        "category": labels[best],
        "confidence": round(confidence, 4),
        "model": model["model"],
        "model_version": model["version"],
        "trained": True,
        "needs_review": confidence < confidence_threshold,
    }


def classify_complaint(description, training_rows, confidence_threshold=0.55):
    usable = [
        row for row in training_rows
        if row["description"] and row["category"]
    ]
    labels = {row["category"] for row in usable}
    if len(usable) < 4 or len(labels) < 2:
        return {
            "category": None,
            "confidence": None,
            "model": "tfidf-logistic-regression",
            "model_version": None,
            "trained": False,
            "needs_review": True,
        }
    return predict_with_tfidf_model(
        description, fit_tfidf_classifier(usable), confidence_threshold
    )


def predict_priority(category, description):
    text = f"{category or ''} {description or ''}".lower()
    critical_terms = (
        "life threatening", "electrocution", "collapse", "contaminated water",
        "sewage overflow", "injury", "fire",
    )
    high_terms = (
        "urgent", "dangerous", "hazard", "flood", "burst", "exposed wire",
        "blocked drain", "hospital", "school",
    )
    low_terms = ("minor", "cosmetic", "small crack", "not urgent")
    if any(term in text for term in critical_terms):
        priority = "Critical"
    elif any(term in text for term in high_terms):
        priority = "High"
    elif any(term in text for term in low_terms):
        priority = "Low"
    else:
        priority = "Medium"
    return {"priority": priority, "method": "transparent severity keyword rules"}


def analyze_urgency(description):
    text = (description or "").lower()
    urgent_terms = ("urgent", "immediately", "danger", "dangerous", "hazard", "flood", "injury")
    dissatisfied_terms = ("still not", "again", "ignored", "unacceptable", "frustrated", "days")
    negative_terms = ("broken", "leaking", "overflow", "blocked", "dirty", "ignored", "unacceptable", "frustrated", "dangerous")
    positive_terms = ("thank", "fixed", "helpful", "resolved", "good")
    urgency = min(1.0, sum(term in text for term in urgent_terms) / 2)
    dissatisfaction = min(1.0, sum(term in text for term in dissatisfied_terms) / 2)
    positive_count = sum(term in text for term in positive_terms)
    negative_count = sum(term in text for term in negative_terms)
    sentiment = (
        (positive_count - negative_count) / (positive_count + negative_count)
        if positive_count + negative_count else 0
    )
    return {
        "urgency_score": round(urgency, 2),
        "dissatisfaction_score": round(dissatisfaction, 2),
        "sentiment_score": round(sentiment, 2),
        "sentiment_label": "negative" if sentiment < -0.1 else "positive" if sentiment > 0.1 else "neutral/unknown",
        "method": "transparent keyword indicators; not an emotion or severity determination",
    }


def evaluate_classifier(training_rows):
    rows = [
        {**dict(row), "_cv_key": row["id"] if "id" in row.keys() else index}
        for index, row in enumerate(training_rows)
        if row["description"] and row["category"]
    ]
    labels = sorted({row["category"] for row in rows})
    category_counts = Counter(row["category"] for row in rows)
    if (
        len(labels) < 2
        or any(category_counts[label] < MIN_EXAMPLES_PER_CATEGORY for label in labels)
    ):
        return {
            "status": "insufficient_data",
            "evaluation": "stratified k-fold cross-validation",
            "minimum_examples_per_category": MIN_EXAMPLES_PER_CATEGORY,
            "training_samples": len(rows),
            "evaluated_samples": 0,
            "category_counts": dict(sorted(category_counts.items())),
            "accuracy": None,
            "macro_precision": None,
            "macro_recall": None,
            "macro_f1": None,
            "confusion_matrix": {},
            "reliability_claim": False,
            "limitations": (
                "Insufficient verified labels for stratified evaluation. "
                "No accuracy is reported and predictions remain advisory."
            ),
        }
    fold_count = min(MAX_STRATIFIED_FOLDS, min(category_counts.values()))
    folds = [[] for _ in range(fold_count)]
    for label in labels:
        class_rows = [row for row in rows if row["category"] == label]
        class_rows.sort(key=lambda row: hashlib.sha256(
            f"{row['category']}\0{row['description']}\0{row['_cv_key']}".encode("utf-8")
        ).hexdigest())
        for index, row in enumerate(class_rows):
            folds[index % fold_count].append(row)
    confusion = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    correct = 0
    evaluated = 0
    fold_metrics = []
    for fold in folds:
        test_keys = {
            hashlib.sha256(
                f"{row['category']}\0{row['description']}\0{row['_cv_key']}".encode("utf-8")
            ).hexdigest()
            for row in fold
        }
        train = [
            row for row in rows
            if hashlib.sha256(
                f"{row['category']}\0{row['description']}\0{row['_cv_key']}".encode("utf-8")
            ).hexdigest() not in test_keys
        ]
        model = fit_tfidf_classifier(train)
        fold_correct = 0
        for row in fold:
            prediction = predict_with_tfidf_model(row["description"], model, 0)
            predicted = prediction["category"]
            if predicted not in labels:
                continue
            evaluated += 1
            confusion[row["category"]][predicted] += 1
            fold_correct += predicted == row["category"]
            correct += predicted == row["category"]
        fold_metrics.append({
            "test_samples": len(fold),
            "accuracy": round(fold_correct / len(fold), 4) if fold else None,
        })
    precision_values = []
    recall_values = []
    f1_values = []
    evaluated_categories = [
        label for label in labels if sum(confusion[label].values()) > 0
    ]
    for label in evaluated_categories:
        true_positive = confusion[label][label]
        predicted_count = sum(confusion[actual][label] for actual in labels)
        actual_count = sum(confusion[label].values())
        precision = true_positive / predicted_count if predicted_count else 0
        recall = true_positive / actual_count if actual_count else 0
        precision_values.append(precision)
        recall_values.append(recall)
        f1_values.append(2 * precision * recall / (precision + recall) if precision + recall else 0)
    return {
        "status": "evaluated_advisory",
        "evaluation": f"{fold_count}-fold stratified cross-validation",
        "minimum_examples_per_category": MIN_EXAMPLES_PER_CATEGORY,
        "training_samples": len(rows),
        "evaluated_samples": evaluated,
        "category_counts": dict(sorted(category_counts.items())),
        "fold_metrics": fold_metrics,
        "accuracy": round(correct / evaluated, 4) if evaluated else None,
        "evaluated_categories": evaluated_categories,
        "macro_precision": round(sum(precision_values) / len(evaluated_categories), 4) if evaluated_categories else None,
        "macro_recall": round(sum(recall_values) / len(evaluated_categories), 4) if evaluated_categories else None,
        "macro_f1": round(sum(f1_values) / len(evaluated_categories), 4) if evaluated_categories else None,
        "confusion_matrix": confusion,
        "reliability_claim": False,
        "limitations": (
            "Metrics describe this verified dataset only. They are not a production "
            "reliability claim; predictions remain advisory and never control routing."
        ),
    }


def serialize_model(model):
    return json.dumps(model, sort_keys=True, separators=(",", ":"))


def similar_complaints(target, candidates, limit=3):
    target_text = f"{target['category']} {target['title']} {target['description']}"
    texts = [target_text] + [
        f"{row['category']} {row['title']} {row['description']}"
        for row in candidates
    ]
    _, _, vectors = tfidf_vectors(texts)
    base = vectors[0]
    results = []
    for candidate, vector in zip(candidates, vectors[1:]):
        similarity = sum(base.get(word, 0) * value for word, value in vector.items())
        if similarity > 0:
            results.append({
                "id": candidate["complaint_id"],
                "category": candidate["category"],
                "status": candidate["workflow_status"] or candidate["status"],
                "similarity": round(similarity, 3),
            })
    return sorted(results, key=lambda item: item["similarity"], reverse=True)[:limit]


def estimate_completion(database, category, department, priority, now, fallback_hours=72):
    historical_priority = "High" if priority == "Critical" else priority
    rows = database.execute(
        """SELECT c.created_at, MIN(h.changed_at) AS completed_at
           FROM complaints c
           JOIN department_status_history h ON h.complaint_id = c.complaint_id
           WHERE c.category = ? AND c.assigned_department = ?
             AND c.priority = ?
             AND h.new_status = 'Completed'
           GROUP BY c.complaint_id
           ORDER BY completed_at DESC LIMIT 100""",
        (category, department, historical_priority),
    ).fetchall()
    durations = []
    for row in rows:
        try:
            duration = (
                datetime.fromisoformat(row["completed_at"])
                - datetime.fromisoformat(row["created_at"])
            ).total_seconds() / 3600
        except (TypeError, ValueError):
            continue
        if duration > 0:
            durations.append(duration)
    if len(durations) >= 5:
        durations.sort()
        hours = durations[len(durations) // 2]
        method = "historical median"
    else:
        workload = database.execute(
            """SELECT COUNT(*) FROM complaints
               WHERE assigned_department = ?
                 AND COALESCE(workflow_status, status) NOT IN ('Completed', 'Resolved')""",
            (department,),
        ).fetchone()[0]
        multiplier = {"Critical": 1.5, "High": 1.3, "Medium": 1.0, "Low": 0.85}.get(priority, 1.0)
        hours = fallback_hours * multiplier * min(1.5, 1 + workload * 0.05)
        method = "configurable rule-based fallback"
    return {
        "expected_completion_at": (now + timedelta(hours=hours)).isoformat(timespec="seconds"),
        "estimated_hours": round(hours, 1),
        "method": method,
        "is_guarantee": False,
        "historical_sample_count": len(durations),
    }


def hotspot_clusters(rows, precision=2):
    clusters = {}
    for row in rows:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        key = (round(row["latitude"], precision), round(row["longitude"], precision))
        cluster = clusters.setdefault(key, {"latitude": key[0], "longitude": key[1], "count": 0, "complaint_ids": []})
        cluster["count"] += 1
        cluster["complaint_ids"].append(row["complaint_id"])
    return sorted(
        (cluster for cluster in clusters.values() if cluster["count"] > 1),
        key=lambda item: item["count"],
        reverse=True,
    )


def send_msg91(app, phone, message, complaint_id, department, status, expected_time):
    config_keys = {
        "MSG91_AUTH_KEY": app.config.get("MSG91_AUTH_KEY"),
        "MSG91_TEMPLATE_ID": app.config.get("MSG91_TEMPLATE_ID"),
        "MSG91_SENDER_ID": app.config.get("MSG91_SENDER_ID"),
        "MSG91_DLT_PE_ID": app.config.get("MSG91_DLT_PE_ID"),
        "MSG91_DLT_TEMPLATE_ID": app.config.get("MSG91_DLT_TEMPLATE_ID"),
    }
    missing = [key for key, value in config_keys.items() if not value]
    if missing:
        return (
            "not_configured",
            None,
            f"Missing MSG91 configuration: {', '.join(missing)}.",
        )
    auth_key = config_keys["MSG91_AUTH_KEY"]
    template_id = config_keys["MSG91_TEMPLATE_ID"]
    sender_id = config_keys["MSG91_SENDER_ID"]
    normalized = normalize_indian_mobile(phone)
    if not normalized:
        return "failed", None, "The registered number is not a valid Indian mobile number."
    recipients = [{
        "mobiles": normalized[1:],
        "VAR1": complaint_id,
        "VAR2": department,
        "VAR3": status,
        "VAR4": expected_time or "Not estimated",
    }]
    payload = json.dumps({
        "template_id": template_id,
        "sender": sender_id,
        "recipients": recipients,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://control.msg91.com/api/v5/flow/",
        data=payload,
        headers={"authkey": auth_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            safe_body = body.replace(auth_key, "[redacted]")[:4096]
            if not 200 <= response.status < 300:
                return "failed", safe_body, f"MSG91 returned HTTP {response.status}."
            try:
                provider_result = json.loads(body)
            except json.JSONDecodeError:
                return "failed", safe_body, "MSG91 returned an invalid JSON response."
            if (
                not isinstance(provider_result, dict)
                or str(provider_result.get("type", "")).lower() != "success"
            ):
                detail = provider_result.get("message") if isinstance(provider_result, dict) else None
                detail = str(detail or "MSG91 did not confirm request acceptance.")
                detail = detail.replace(auth_key, "[redacted]")[:500]
                return "failed", safe_body, detail
            provider_status = str(
                provider_result.get("delivery_status")
                or provider_result.get("status")
                or ""
            ).lower()
            if provider_status in {"failed", "rejected", "error"}:
                detail = str(
                    provider_result.get("message")
                    or "MSG91 reported that the message failed."
                ).replace(auth_key, "[redacted]")[:500]
                return "failed", safe_body, detail
            return ("delivered" if provider_status == "delivered" else "sent"), safe_body, None
    except urllib.error.HTTPError as error:
        try:
            body = error.read(4096).decode("utf-8", errors="replace")
        except OSError:
            body = ""
        safe_body = body.replace(auth_key, "[redacted]")[:4096]
        return "failed", safe_body, f"MSG91 returned HTTP {error.code}."
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        detail = str(getattr(error, "reason", error)).replace(auth_key, "[redacted]")[:500]
        return "failed", None, f"MSG91 request failed: {detail}"


def normalize_indian_mobile(phone):
    if not isinstance(phone, str):
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return f"+{digits}"
    if len(digits) == 14 and digits.startswith("0091") and digits[4] in "6789":
        return f"+91{digits[4:]}"
    return None


def send_brevo_email(app, email, subject, body):
    config = app.config
    api_key = config.get("BREVO_API_KEY")
    sender_email = config.get("BREVO_SENDER_EMAIL")
    sender_name = config.get("BREVO_SENDER_NAME") or "SmartCivicAI"
    missing = [
        key for key, value in (
            ("BREVO_API_KEY", api_key),
            ("BREVO_SENDER_EMAIL", sender_email),
        )
        if not value
    ]
    if missing:
        return "not_configured", None, f"Missing Brevo configuration: {', '.join(missing)}."
    payload = json.dumps({
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": email}],
        "subject": subject,
        "textContent": body,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read(4096).decode("utf-8", errors="replace")
            safe_body = response_body.replace(api_key, "[redacted]")[:4096]
            if response.status != 201:
                return "failed", safe_body, f"Brevo returned HTTP {response.status}."
            try:
                provider_result = json.loads(response_body)
            except json.JSONDecodeError:
                return "failed", safe_body, "Brevo returned an invalid JSON response."
            if not isinstance(provider_result, dict) or not provider_result.get("messageId"):
                return "failed", safe_body, "Brevo did not confirm email acceptance."
            return "sent", safe_body, None
    except urllib.error.HTTPError as error:
        try:
            response_body = error.read(4096).decode("utf-8", errors="replace")
        except OSError:
            response_body = ""
        safe_body = response_body.replace(api_key, "[redacted]")[:4096]
        return "failed", safe_body, f"Brevo returned HTTP {error.code}."
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        detail = str(getattr(error, "reason", error)).replace(api_key, "[redacted]")[:500]
        return "failed", None, f"Brevo request failed: {detail}"


def dispatch_citizen_notification(
    app, complaint_id, event_key, kind, message, channels=("sms", "email"),
):
    connection = sqlite3.connect(app.config["DATABASE"])
    connection.row_factory = sqlite3.Row
    try:
        complaint = connection.execute(
            """SELECT c.complaint_id, c.assigned_department, c.status,
                      c.workflow_status, c.expected_completion_at,
                      u.id AS user_id, u.email, u.phone, u.sms_consent
               FROM complaints c JOIN users u ON u.id = c.citizen_id
               WHERE c.complaint_id = ?""",
            (complaint_id,),
        ).fetchone()
        if complaint is None:
            raise ValueError(f"Complaint {complaint_id} was not found for notification.")
        expected = complaint["workflow_status"] or complaint["status"]
        expected_time = complaint["expected_completion_at"]
        deliveries = []
        for channel in channels:
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            delivery_message = (
                f"Complaint {complaint_id}\n{message}\n"
                f"Department: {complaint['assigned_department']}\n"
                f"Status: {expected}\nEstimated completion: {expected_time or 'Not set'} "
                "(estimate only)."
            )
            claimed = connection.execute(
                """INSERT OR IGNORE INTO notification_deliveries
                   (user_id, complaint_id, channel, event_key, status, message,
                    progress_note, attempts, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?, 0, ?, ?)""",
                (complaint["user_id"], complaint_id, channel, event_key,
                 delivery_message, None, created_at, created_at),
            )
            connection.commit()
            if not claimed.rowcount:
                continue
            try:
                if channel == "sms":
                    if not complaint["sms_consent"]:
                        result = ("skipped", None, "Citizen has not consented to SMS.")
                    elif not normalize_indian_mobile(complaint["phone"]):
                        result = ("failed", None, "The registered number is not a valid Indian mobile number.")
                    else:
                        sender = app.config.get("SMS_SENDER") or send_msg91
                        result = sender(
                            app, complaint["phone"], delivery_message, complaint_id,
                            complaint["assigned_department"], expected, expected_time,
                        )
                else:
                    sender = app.config.get("BREVO_SENDER") or send_brevo_email
                    result = sender(
                        app, complaint["email"],
                        f"SmartCivicAI complaint {complaint_id}: {kind.replace('_', ' ').title()}",
                        delivery_message,
                    )
            except Exception as error:
                connection.execute(
                    """UPDATE notification_deliveries
                       SET status = 'failed', failure_detail = ?, attempts = 1,
                           updated_at = ? WHERE complaint_id = ? AND channel = ?
                             AND event_key = ? AND status = 'pending'""",
                    (str(error), datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     complaint_id, channel, event_key),
                )
                connection.commit()
                raise
            status, provider_response, error = result
            updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            connection.execute(
                """UPDATE notification_deliveries
                   SET status = ?, provider_response = ?, failure_detail = ?,
                       attempts = 1, updated_at = ?
                   WHERE complaint_id = ? AND channel = ? AND event_key = ?
                     AND status = 'pending'""",
                (status, provider_response, error, updated_at,
                 complaint_id, channel, event_key),
            )
            connection.commit()
            deliveries.append({"channel": channel, "status": status, "error": error})
        return deliveries
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def retry_delivery(app, delivery_id):
    connection = sqlite3.connect(app.config["DATABASE"])
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        delivery = connection.execute(
            """SELECT d.*, c.assigned_department,
                      c.status AS complaint_status, c.workflow_status,
                      c.expected_completion_at, u.email, u.phone, u.sms_consent
               FROM notification_deliveries d
               JOIN complaints c ON c.complaint_id = d.complaint_id
               JOIN users u ON u.id = d.user_id
               WHERE d.id = ?""",
            (delivery_id,),
        ).fetchone()
        if delivery is None:
            raise LookupError("Notification delivery was not found.")
        if delivery["status"] not in {"failed", "not_configured"}:
            connection.commit()
            return {
                "id": delivery["id"],
                "status": delivery["status"],
                "channel": delivery["channel"],
                "event_key": delivery["event_key"],
                "attempts": delivery["attempts"],
            }
        connection.execute(
            """UPDATE notification_deliveries SET status = 'pending',
                      updated_at = ? WHERE id = ? AND status IN ('failed', 'not_configured')""",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), delivery_id),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            connection.commit()
            return {"id": delivery_id, "status": "pending"}
        connection.commit()
        message = (
            delivery["message"]
            or f"SmartCivicAI {delivery['complaint_id']}: {delivery['assigned_department']}; "
            f"status {delivery['workflow_status'] or delivery['complaint_status']}."
        )
        try:
            if delivery["channel"] == "sms":
                if not delivery["sms_consent"]:
                    result = ("skipped", None, "Citizen has not consented to SMS.")
                elif not normalize_indian_mobile(delivery["phone"]):
                    result = ("failed", None, "The registered number is not a valid Indian mobile number.")
                else:
                    sender = app.config.get("SMS_SENDER") or send_msg91
                    result = sender(
                        app, delivery["phone"], message, delivery["complaint_id"],
                        delivery["assigned_department"],
                        delivery["workflow_status"] or delivery["complaint_status"],
                        delivery["expected_completion_at"],
                    )
            else:
                sender = app.config.get("BREVO_SENDER") or send_brevo_email
                result = sender(
                    app, delivery["email"],
                    f"SmartCivicAI complaint {delivery['complaint_id']}: notification retry",
                    message,
                )
            status, provider_response, error = result
        except Exception as error:
            connection.execute(
                """UPDATE notification_deliveries
                   SET status = 'failed', failure_detail = ?, attempts = attempts + 1,
                       updated_at = ? WHERE id = ? AND status = 'pending'""",
                (str(error), datetime.now(timezone.utc).isoformat(timespec="seconds"), delivery_id),
            )
            connection.commit()
            raise
        connection.execute(
            """UPDATE notification_deliveries
               SET status = ?, provider_response = ?, failure_detail = ?,
                   attempts = attempts + 1, updated_at = ?
               WHERE id = ? AND status NOT IN ('sent', 'skipped')""",
            (status, provider_response, error,
             datetime.now(timezone.utc).isoformat(timespec="seconds"), delivery_id),
        )
        connection.commit()
        return {"id": delivery_id, "status": status, "error": error}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
