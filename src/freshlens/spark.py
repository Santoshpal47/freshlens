"""SparkSession factory.

* On Databricks the active session is reused (Delta is built in).
* Locally we start Spark with Delta Lake, pinned to the loopback interface. Without that,
  macOS hostname resolution can stall a single stage for minutes.
"""

from __future__ import annotations

import os
from pathlib import Path

from pyspark.sql import SparkSession

from freshlens.config import PROJECT_ROOT


def _ensure_java() -> None:
    if os.environ.get("JAVA_HOME"):
        return
    jdks = sorted((PROJECT_ROOT / ".jdk").glob("jdk-17*"))
    if jdks:
        home = jdks[-1] / "Contents" / "Home"  # macOS layout
        os.environ["JAVA_HOME"] = str(home if home.exists() else jdks[-1])


def on_databricks() -> bool:
    return "DATABRICKS_RUNTIME_VERSION" in os.environ


def get_spark(app_name: str = "freshlens") -> SparkSession:
    if on_databricks():
        return SparkSession.builder.getOrCreate()

    from delta import configure_spark_with_delta_pip

    _ensure_java()
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    warehouse = Path(os.environ.get("FPR_DATA_ROOT", PROJECT_ROOT / "data")) / "spark-warehouse"
    builder = (
        SparkSession.builder.master(os.environ.get("FPR_SPARK_MASTER", "local[*]"))
        .appName(app_name)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", os.environ.get("FPR_SHUFFLE_PARTITIONS", "8"))
        .config("spark.databricks.delta.snapshotPartitions", "2")
        .config("spark.sql.session.timeZone", "Asia/Kolkata")
        .config("spark.sql.warehouse.dir", str(warehouse))
        .config("spark.driver.memory", os.environ.get("FPR_DRIVER_MEMORY", "2g"))
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
