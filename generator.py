import time
import test_functions
import random

# initialize list grid that will hold individual rows (lists) to form the entire puzzle
grid = []
# initialize list that will hold initial random row and all subsequent shuffled rows
new_row = [0, 0, 0, 0, 0, 0, 0, 0, 0]
number_of_rows = 0

# for loop generates initial row and checks for uniqueness
for i in range(9):
    while new_row[i] == 0:
        new_value = random.randint(1, 9)
        if new_value not in new_row:
            new_row[i] = new_value

# use of append(list.copy()) in order to pass values to grid instead of reference
grid.append(new_row.copy())
number_of_rows += 1

# for loop will iterate 8 times in order to generate remaining 8 rows. Starts at 1 to keep track of place in puzzle
for y in range(1, 9):
    # random.shuffle is used to randomly mix the unique list created earlier
    random.shuffle(new_row)
    exit_while = False
    while exit_while == False:
        # if on last row, determine necessary row instead of randomly stumbling upon it.
        if y == 8:
            grid.append([0, 0, 0, 0, 0, 0, 0, 0, 0])
            if y == 8:
                for sumX in range(9):
                    sum = 0
                    for sumY in range(9):
                        # sum of all numbers in a column/row should equal 45.
                        if sumY < 8:
                            sum += grid[sumY][sumX]
                        else:
                            grid[sumY][sumX] = 45 - sum
            exit_while = True
        # test if new row passes column test and box test
        elif test_functions.check_col(grid, new_row, number_of_rows) and \
                test_functions.check_box(grid, y, new_row, number_of_rows):
            # if so, exit while loop
            exit_while = True
            grid.append(new_row.copy())
        else:
            # if not, generate new row and check again
            random.shuffle(new_row)
    number_of_rows += 1

# used for testing output
print(*grid, sep="\n")