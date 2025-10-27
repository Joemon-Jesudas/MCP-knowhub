import os
from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from typing import Dict, List, Any, Optional
import json
from dotenv import load_dotenv
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP()

# Database configuration - read from environment variables
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", None)
DB_USER = os.getenv("DB_USER", None)
DB_PASSWORD = os.getenv("DB_PASSWORD", None)


# Create SQLAlchemy engine and session
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = None
Session = None

def initialize_database():
    """Initialize database connection using SQLAlchemy"""
    global engine, Session
    try:
        engine = create_engine(DATABASE_URL)
        Session = sessionmaker(bind=engine)
        return True
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        return False


@mcp.tool()
def list_tables() -> List[str]:
    """
    List all tables in the PostgreSQL database.
    Returns a list of table names.
    """
    try:
        if engine is None:
            initialize_database()

        inspector = inspect(engine)
        tables = inspector.get_table_names()
        return tables
    except SQLAlchemyError as e:
        return [f"Error listing tables: {str(e)}"]


@mcp.tool()
def describe_table(table_name: str) -> Dict[str, Any]:
    """
    Get detailed schema information for a specific table.

    Args:
        table_name: Name of the table to describe

    Returns:
        Dictionary containing column names, types, and constraints
    """
    try:
        if engine is None:
            initialize_database()

        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)
        primary_keys = inspector.get_pk_constraint(table_name)
        foreign_keys = inspector.get_foreign_keys(table_name)

        return {
            "table_name": table_name,
            "columns": [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col["nullable"],
                    "default": col.get("default")
                }
                for col in columns
            ],
            "primary_keys": primary_keys.get("constrained_columns", []),
            "foreign_keys": [
                {
                    "columns": fk["constrained_columns"],
                    "referred_table": fk["referred_table"],
                    "referred_columns": fk["referred_columns"]
                }
                for fk in foreign_keys
            ]
        }
    except SQLAlchemyError as e:
        return {"error": f"Error describing table: {str(e)}"}


@mcp.tool()
def execute_query(sql_query: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute a SQL query against the PostgreSQL database.
    Use this tool to run SELECT queries based on natural language questions.

    Args:
        sql_query: The SQL SELECT query to execute
        params: Optional dictionary of parameters for parameterized queries

    Returns:
        Dictionary containing query results and metadata
    """
    try:
        if engine is None:
            initialize_database()

        # Security: Only allow SELECT statements
        normalized_query = sql_query.strip().upper()
        if not normalized_query.startswith("SELECT"):
            return {
                "error": "Only SELECT queries are allowed for security reasons",
                "query": sql_query
            }

        session = Session()
        try:
            # Execute query with parameters if provided
            if params:
                result = session.execute(text(sql_query), params)
            else:
                result = session.execute(text(sql_query))

            # Fetch all results
            rows = result.fetchall()
            columns = result.keys()

            # Convert to list of dictionaries
            data = [
                {col: val for col, val in zip(columns, row)}
                for row in rows
            ]

            return {
                "success": True,
                "row_count": len(data),
                "columns": list(columns),
                "data": data,
                "query": sql_query
            }
        finally:
            session.close()

    except SQLAlchemyError as e:
        return {
            "success": False,
            "error": str(e),
            "query": sql_query
        }
    

@mcp.tool()
def generate_visualization(natural_language_query: str,sql_query: str,
                           chart_type: str = "auto") -> Dict[str, Any]:
    """
    Generate a visualization (chart/graph) based on query results.
    This tool creates visual representations of data to enhance insights.

    Use this tool when users ask questions like:
    - "Who has the highest spend in 2025?"
    - "Show me sales by month"
    - "Compare revenue across regions"

    Args:
        natural_language_query: The original user question
        sql_query: The SQL query to execute for getting data
        chart_type: Type of chart - 'auto', 'bar', 'line', 'pie', 'scatter'
                   'auto' will intelligently choose based on data

    Returns:
         Returns base64-encoded HTML (Plotly)
    """
    try:
        if engine is None:
            initialize_database()

        # Execute the query first
        query_result = execute_query(sql_query)

        if not query_result.get("success", False):
            return {
                "success": False,
                "error": f"Query execution failed: {query_result.get('error', 'Unknown error')}",
                "query": sql_query
            }

        data = query_result.get("data", [])
        columns = query_result.get("columns", [])

        if not data:
            return {
                "success": False,
                "error": "No data returned from query",
                "query": sql_query
            }

        # Analyze data structure
        numeric_columns = []
        text_columns = []
        date_columns = []

        for col in columns:
            sample_value = data[0].get(col)
            if sample_value is not None:
                if isinstance(sample_value, (int, float)):
                    numeric_columns.append(col)
                elif isinstance(sample_value, str):
                    # Check if it's a date string
                    if any(keyword in col.lower() for keyword in ['date', 'time', 'month', 'year']):
                        date_columns.append(col)
                    else:
                        text_columns.append(col)

        # Auto-detect chart type if needed
        if chart_type == "auto":
            if len(numeric_columns) >= 2:
                chart_type = "scatter"
            elif len(numeric_columns) == 1 and len(text_columns) >= 1:
                # For ranking/comparison queries (like "highest spend")
                if any(word in natural_language_query.lower() for word in ['highest', 'lowest', 'top', 'bottom', 'most', 'least']):
                    chart_type = "bar"
                else:
                    chart_type = "pie" if len(data) <= 10 else "bar"
            elif len(numeric_columns) == 1 and len(date_columns) >= 1:
                chart_type = "line"
            else:
                chart_type = "bar"

        # Prepare chart data based on type
        chart_data = {
            "success": True,
            "chart_type": chart_type,
            "title": natural_language_query,
            "data": data,
            "columns": columns,
            "numeric_columns": numeric_columns,
            "text_columns": text_columns,
            "date_columns": date_columns,
            "row_count": len(data),
            "query": sql_query
        }

        # Add chart-specific recommendations
        if chart_type == "bar":
            chart_data["x_axis"] = text_columns[0] if text_columns else columns[0]
            chart_data["y_axis"] = numeric_columns[0] if numeric_columns else columns[1]
            chart_data["description"] = f"Bar chart showing {natural_language_query}"

        elif chart_type == "line":
            chart_data["x_axis"] = date_columns[0] if date_columns else columns[0]
            chart_data["y_axis"] = numeric_columns[0] if numeric_columns else columns[1]
            chart_data["description"] = f"Line chart showing trend for {natural_language_query}"

        elif chart_type == "pie":
            chart_data["label_column"] = text_columns[0] if text_columns else columns[0]
            chart_data["value_column"] = numeric_columns[0] if numeric_columns else columns[1]
            chart_data["description"] = f"Pie chart showing distribution for {natural_language_query}"

        elif chart_type == "scatter":
            chart_data["x_axis"] = numeric_columns[0] if len(numeric_columns) > 0 else columns[0]
            chart_data["y_axis"] = numeric_columns[1] if len(numeric_columns) > 1 else columns[1]
            chart_data["description"] = f"Scatter plot analyzing {natural_language_query}"

        return chart_data

    except Exception as e:
        return {
            "success": False,
            "error": f"Visualization generation failed: {str(e)}",
            "query": sql_query
        }


# Initialize database on startup
if __name__ == "__main__":
    if initialize_database():
        print("Database connection initialized successfully")
        print(f"Connected to: {DB_NAME}@{DB_HOST}:{DB_PORT}")
    else:
        print("Failed to initialize database connection")
        print("Please check your database credentials in .env file")
    # Run the MCP server
    mcp.run()
