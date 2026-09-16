from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3
import json

from gis_service import distance_and_bearing, geometry_intersection, point_in_eez
from sar_drift import predict_drift
from sar_search_zone import create_search_zone
from pfz_service import create_pfz_zone


app = FastAPI(title="ORCA GIS + SAR API")


# ============================================================
# Request Models
# ============================================================

class DistanceRequest(BaseModel):
    lat1: float
    lon1: float
    lat2: float
    lon2: float


class IntersectionRequest(BaseModel):
    geometry_a: dict
    geometry_b: dict


class SARCreateRequest(BaseModel):
    latitude: float
    longitude: float


class PFZRequest(BaseModel):
    latitude: float
    longitude: float
    radius_km: float = 5.0


class SARDiftRequest(BaseModel):
    incident_id: int
    current_speed_knots: float
    current_direction_degrees: float
    wind_speed_knots: float
    wind_direction_degrees: float
    hours: float


class SARLocationRequest(BaseModel):
    incident_id: int
    latitude: float
    longitude: float


# ============================================================
# GIS Endpoints
# ============================================================

@app.post("/api/geospatial/distance")
def calculate_distance(request: DistanceRequest):
    return distance_and_bearing(
        request.lat1,
        request.lon1,
        request.lat2,
        request.lon2,
    )


@app.post("/api/geospatial/intersection")
def calculate_intersection(request: IntersectionRequest):
    return geometry_intersection(
        request.geometry_a,
        request.geometry_b,
    )


@app.post("/api/geospatial/eez")
def check_eez(request: SARCreateRequest):
    return point_in_eez(
        request.latitude,
        request.longitude,
    )


@app.post("/api/geospatial/pfz")
def create_pfz(request: PFZRequest):
    return create_pfz_zone(
        request.latitude,
        request.longitude,
        request.radius_km,
    )


@app.post("/api/route/analyze")
def analyze_route(request: DistanceRequest):
    result = distance_and_bearing(
        request.lat1,
        request.lon1,
        request.lat2,
        request.lon2,
    )

    return {
        "route": {
            "start": {
                "latitude": request.lat1,
                "longitude": request.lon1,
            },
            "end": {
                "latitude": request.lat2,
                "longitude": request.lon2,
            },
        },
        "distance_km": result["distance_km"],
        "bearing_degrees": result["bearing_degrees"],
        "status": "route analyzed",
    }


# ============================================================
# SAR Incident
# ============================================================

@app.post("/api/sar/create")
def create_sar_incident(request: SARCreateRequest):
    conn = sqlite3.connect("orca_cache.db")

    cursor = conn.execute(
        """
        INSERT INTO sar_incidents
        (status, last_known_latitude, last_known_longitude)
        VALUES (?, ?, ?)
        """,
        (
            "active",
            request.latitude,
            request.longitude,
        ),
    )

    incident_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "incident_id": incident_id,
        "status": "active",
        "last_known_latitude": request.latitude,
        "last_known_longitude": request.longitude,
    }


# ============================================================
# SAR Drift Prediction
# ============================================================

@app.post("/api/sar/predict-drift")
def predict_sar_drift(request: SARDiftRequest):
    conn = sqlite3.connect("orca_cache.db")

    incident = conn.execute(
        """
        SELECT last_known_latitude, last_known_longitude
        FROM sar_incidents
        WHERE id = ?
        """,
        (request.incident_id,),
    ).fetchone()

    if incident is None:
        conn.close()
        return {
            "error": "SAR incident not found"
        }

    latitude, longitude = incident

    prediction = predict_drift(
        latitude,
        longitude,
        request.current_speed_knots,
        request.current_direction_degrees,
        request.wind_speed_knots,
        request.wind_direction_degrees,
        request.hours,
    )

    conn.execute(
        """
        INSERT INTO sar_predictions
        (
            incident_id,
            predicted_latitude,
            predicted_longitude,
            uncertainty_km
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            request.incident_id,
            prediction["predicted_latitude"],
            prediction["predicted_longitude"],
            prediction["uncertainty_km"],
        ),
    )

    conn.commit()
    conn.close()

    return {
        "incident_id": request.incident_id,
        "prediction": prediction,
    }


# ============================================================
# SAR Location History
# ============================================================

@app.post("/api/sar/location")
def add_sar_location(request: SARLocationRequest):
    conn = sqlite3.connect("orca_cache.db")

    incident = conn.execute(
        """
        SELECT id
        FROM sar_incidents
        WHERE id = ?
        """,
        (request.incident_id,),
    ).fetchone()

    if incident is None:
        conn.close()
        return {
            "error": "SAR incident not found"
        }

    conn.execute(
        """
        INSERT INTO sar_location_history
        (incident_id, latitude, longitude)
        VALUES (?, ?, ?)
        """,
        (
            request.incident_id,
            request.latitude,
            request.longitude,
        ),
    )

    conn.execute(
        """
        UPDATE sar_incidents
        SET
            last_known_latitude = ?,
            last_known_longitude = ?
        WHERE id = ?
        """,
        (
            request.latitude,
            request.longitude,
            request.incident_id,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "incident_id": request.incident_id,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "status": "location recorded",
    }


# ============================================================
# SAR Search Zone Generation
# ============================================================

@app.post("/api/sar/{incident_id}/search-zones")
def generate_search_zone(incident_id: int):
    conn = sqlite3.connect("orca_cache.db")

    prediction = conn.execute(
        """
        SELECT
            predicted_latitude,
            predicted_longitude,
            uncertainty_km
        FROM sar_predictions
        WHERE incident_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (incident_id,),
    ).fetchone()

    if prediction is None:
        conn.close()
        return {
            "error": "No SAR prediction found"
        }

    latitude, longitude, uncertainty_km = prediction

    zone = create_search_zone(
        latitude,
        longitude,
        uncertainty_km,
    )

    conn.execute(
        """
        INSERT INTO sar_search_zones
        (incident_id, geometry, probability)
        VALUES (?, ?, ?)
        """,
        (
            incident_id,
            json.dumps(zone["geometry"]),
            1.0,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "incident_id": incident_id,
        "search_zone": zone,
    }


# ============================================================
# Get SAR Incident
# ============================================================

@app.get("/api/sar/{incident_id}")
def get_sar_incident(incident_id: int):
    conn = sqlite3.connect("orca_cache.db")

    incident = conn.execute(
        """
        SELECT
            id,
            status,
            last_known_latitude,
            last_known_longitude,
            created_at
        FROM sar_incidents
        WHERE id = ?
        """,
        (incident_id,),
    ).fetchone()

    conn.close()

    if incident is None:
        return {
            "error": "SAR incident not found"
        }

    return {
        "incident_id": incident[0],
        "status": incident[1],
        "last_known_latitude": incident[2],
        "last_known_longitude": incident[3],
        "created_at": incident[4],
    }


# ============================================================
# Get SAR Search Zones
# ============================================================

@app.get("/api/sar/{incident_id}/search-zones")
def get_search_zones(incident_id: int):
    conn = sqlite3.connect("orca_cache.db")

    zones = conn.execute(
        """
        SELECT
            id,
            geometry,
            probability,
            created_at
        FROM sar_search_zones
        WHERE incident_id = ?
        ORDER BY id DESC
        """,
        (incident_id,),
    ).fetchall()

    conn.close()

    return {
        "incident_id": incident_id,
        "count": len(zones),
        "search_zones": [
            {
                "zone_id": zone[0],
                "geometry": json.loads(zone[1]),
                "probability": zone[2],
                "created_at": zone[3],
            }
            for zone in zones
        ],
    }


# ============================================================
# Get SAR Evidence
# ============================================================

@app.get("/api/sar/{incident_id}/evidence")
def get_sar_evidence(incident_id: int):
    conn = sqlite3.connect("orca_cache.db")

    evidence = conn.execute(
        """
        SELECT
            id,
            evidence_type,
            description,
            source,
            created_at
        FROM sar_evidence
        WHERE incident_id = ?
        ORDER BY id DESC
        """,
        (incident_id,),
    ).fetchall()

    conn.close()

    return {
        "incident_id": incident_id,
        "count": len(evidence),
        "evidence": [
            {
                "evidence_id": item[0],
                "evidence_type": item[1],
                "description": item[2],
                "source": item[3],
                "created_at": item[4],
            }
            for item in evidence
        ],
    }


# ============================================================
# Root
# ============================================================

@app.get("/")
def root():
    return {
        "status": "ORCA GIS + SAR API is running"
    }