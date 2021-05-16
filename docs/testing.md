# Lithops Testing Guidelines

## Verify Installation:
run ``` lithops test``` to run an extensive inspection, which simulates your lithops installation on a variety of tests.
 - Get all available options by running ```lithops test --help```  
 - Get all available test functions by running ```lithops test -t help``` to get a list of the available tests. 
   <br/> Run a single test via ```lithops test -t test_name```.
   <br/> To avoid running all similarly named test functions, prefix the test name in the following way: "TestClass.test_name". 
 - Get all available groups, run ```lithops test -g help```.
    <br/> Run a single group of tests via ```lithops test -g group_name```.
   

## Contribute:

### Be aware to the available resources: 
Whether you're adding a new function, or a new test group you'd be better off knowing the available resources at your disposal:
 - lithops/tests/util_func contains many functions, divided into categories, that you may find helpful.
 - lithops/tests contains a template_file called "test_template" which contains documentation regarding each 
   common resource/import that may interest you.
 - Many examples utilizing said resources may be found across the ""test_*" files of lithops/tests.
 - For a variety of evaluation functions ("assert*") belonging to unittest, browse this [documentation page](https://docs.python.org/3.7/library/unittest.html#module-unittest).

#### Examples:
 - Access the functions in your chosen backend storage class via "STORAGE", e.g. ```STORAGE.put_object```.
 - Access your bucket via ```STORAGE_CONFIG['bucket']```.
 - Pass on "CONFIG" to your function executor instance, to allow your test function to work with users that
   </br> provided a path to the config file via a flag, e.g. ```fexec = lithops.FunctionExecutor(config=CONFIG)```. 

### Add a test to an existing test group: 
In case you'd like to add a test to an existing test group, locate the appropriate test group  
in lithops/tests (indicated by file name) and add your test function appropriately:
 - Add your test function as a method inside the class inheriting from unittest.testcase. 
 - To minimize file length either use existing util functions from lithops/tests/util_func or add new ones to that directory. 
 - A test function that simultaneously tests async, map and map_reduce will be placed at test_map_reduce.py. 
   </br> similarly, a test function that tests both async and map will be placed at test_map.py. 

### Add a new test group: 
Before adding a test function that aims to test an untested feature:  
 - Create a new file in lithops/tests using the template file as your guide:
    - Create a new copy of the template file and name it "test_feature_name", thus automatically creating a new test group named "feature_name". 
    - Figure out which rows are necessary for your new test group, by following documentation 
      beside the rows, then, proceed to un-comment said rows.
      
 - Continue to add the function by adhering to the instructions in the clause above.

