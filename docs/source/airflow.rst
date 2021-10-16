Apache Airflow
==============

Airflow is a platform created by the community to programmatically author, schedule and monitor workflows.
The Airflow/Lithops integration allows Airflow users to keep all of their Ray code in Python functions and
define task dependencies by moving data through python functions.


Refer to the `integration repository <https://github.com/lithops-cloud/airflow-plugin>`_ .

Examples
--------

- Airflow/Lithops example:

Define a function in a separate file (``my_functions.py``):

.. code:: python

    def add(x, y):
	    return x + y


Import the Lithops operator and the function, and create the DAG to execute:

.. code:: python

    from airflow.operators.python_operator import PythonOperator
    from airflow.operators.lithops_airflow_plugin import LithopsMapOperator
    from my_functions import add

    args = {
        'owner': 'lithops',
        'start_date': days_ago(2),
    }

    dag = DAG(
        dag_id='LithopsTest',
        default_args=args,
        schedule_interval=None,
    )

    gen_list = PythonOperator(
        task_id='gen_list',
        python_callable=lambda: [random.randint(1, 100) for _ in range(10)],
        dag=dag
    )

    mult_num_map = LithopsMapOperator(
        task_id='mult_num_map',
        map_function=example_functions.add_num,
        iterdata_from_task={'a': 'gen_list'},
        extra_args={'b': 10},
        dag=dag
    )

    gen_list >> mult_num_map
