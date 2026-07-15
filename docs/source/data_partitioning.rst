Data Partitioning
=================

When using the Lithops ``map`` function to run a single function over a
rather large file, one might consider breaking the workload into smaller
portions, handing each portion to a separate thread. We refer to said
portions as chunks.

Below is an example of using a map function to read a CSV file
stored in COS, split into chunks of a pre-determined size:

.. code:: python

    def line_counter_in_chunk(obj):
        counter = {}
        data = obj.data_stream.read()

        for line in data.decode('utf-8').split('\n'):
            if line not in counter:
                counter[line] = 1
            else:
                counter[line] += 1
        return counter


    if __name__ == "__main__":
        data_location = 'cos://bucket_name/file_name.csv'
        size = int(6.7 * pow(2,20))  # ~6.7MiB - arbitrarily chosen chunk size in bytes 

        fexec = lithops.FunctionExecutor()
        fexec.map(line_counter_in_chunk, data_location, obj_chunk_size=size)
        res = fexec.get_result()

        with open('logs/map_output', 'w') as f:
            f.write(str(res).replace('{','\n{'))

-  To take full advantage of the example above (for the next topic), use a
   file with a fixed number of rows repeated as a routine. You can
   create an example CSV file using the following function:

   .. code:: python

       def create_routine_file():
           """ Creates a ~17MB CSV file consisting of 5 repeating lines. """

           # EOL = end of line identifier for ease of testing
           str_routine = """The Project Gutenberg eBook of Judgments in Vacation, by Edward Abbott Parry EOL1
       This eBook is for the use of anyone anywhere in the United States and EOL2  
       most other parts of the world at no cost and with almost no restrictions EOL3
       whatsoever. You may copy it, give it away or re-use it under the terms EOL4
       of the Project Gutenberg License included with this eBook or online at EOL5"""

           ITERATIONS = 45000
           with open('line_integrity.csv', 'a+') as f:
               for i in range(ITERATIONS):
                   f.write(str_routine)
                   if i < ITERATIONS - 1:
                       f.write('\n')

-  Alternatively, you can replace ``obj_chunk_size`` with the
   ``obj_chunk_number`` parameter to split the file into a known number of
   chunks.

-  You may tinker with the test's parameters, such as uploading files
   of different sizes, altering the chunk size, or running a map function of
   your choosing. As mentioned in the documentation, the chunk size must
   be at least 1 MiB.

Keeping line integrity in mind
------------------------------

One important feature implemented as part of the chunking functionality
is dividing the input file into chunks while making sure no chunk contains
partial lines. Thus, running the test above with any (legal)
configuration of parameters will produce a file consisting solely of
entire rows.

If you opted to follow the recommendation above (regarding the
file contents), you can verify line integrity quickly by replacing the
call to the map function with the following ``map_reduce`` and adding the
``map_function`` below:

.. code:: python

    def count_total_matching_lines(results):
        final_result = {}
        for count in results:
            for line in count:
                if line not in final_result:
                    final_result[line] = count[line]
                else:
                    final_result[line] += count[line]

        return final_result

    fexec.map_reduce(line_counter_in_chunk, data_location, count_total_matching_lines, obj_chunk_size=size)

The next part covers the main details of the chunking procedure, as it's
implemented in the Lithops project.

The algorithm behind the scenes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``map`` or ``map_reduce`` is called, a new job is created (in
``lithops/job/job.py``). The relevant part of the algorithm begins when
``create_partitions`` (in ``lithops/job/partitioner.py``) is called, and the
job's chunks are associated with byte ranges. At this stage, each chunk
simply gets its fair share plus a fixed threshold, whose purpose will become
apparent shortly. These byte ranges are pickled and stored in the cloud.

Later, each thread aggregates (unpickles) from the cloud the relevant
data associated with its own chunk (in ``run()`` of
``lithops/worker/taskrunner.py``), which contains the aforementioned byte
ranges. Among other aggregated objects, a ``data_stream`` object that
handles the line integrity is initialized and appended. Finally,
``taskrunner.py`` passes it all forward to the map function (the reason
the function in the example receives a parameter).

When users wish to read the chunks, they may do so by calling the ``read``
function (the overriding version in ``lithops/utils.py``), which is
implemented as follows:

#. Store the first byte of the current chunk, unless the chunk in question
   is the first or only chunk in the mapping job.

#. Read the whole chunk and store it as a string in the variable
   ``retval``. The total number of bytes stored is treated as the default
   ``last_row_end_pos``.

#. Since the first byte is, as a matter of fact, the last byte of the
   previous chunk, we inspect whether it is a newline (``\n``) or not. If
   not,    it means that the current chunk starts in the middle of a line
   belonging entirely to the former chunk. In such a case,
   position ``first_row_start_pos`` at the beginning of the next line.

#. Because each chunk received an extra amount of bytes (the
   threshold previously mentioned, for the very purpose stated in step 3),
   every chunk except the last one needs to discard the excess rows by
   moving ``last_row_end_pos`` to the beginning of the next row within
   the threshold.

#. Finally, ``retval[first_row_start_pos : last_row_end_pos]``, which
   contains a chunk free from any split lines, is returned.

