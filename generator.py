import test_functions
import random


# generate_grid creates fully completed sudoku puzzle
def generate_grid():
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
                        col_sum = 0
                        for sumY in range(9):
                            # sum of all numbers in a column/row should equal 45.
                            if sumY < 8:
                                col_sum += grid[sumY][sumX]
                            else:
                                grid[sumY][sumX] = 45 - col_sum
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

    return grid


# this function takes in an already generated grid (fully solved sudoku puzzle) and removes numbers in order to create
# the puzzle. Returns a new grid.
# @param grid is a fully solved 9x9 sudoku puzzle stored in a 2D list.
def create_puzzle(grid, number_to_remove):
    # 64 is the maximum number you can remove. Any more than that and you are garunteed a puzzle with more than one
    # solution. The lower the number removed, generally, the easier the puzzle will be.
    number_removed = 0
    new_grid = grid

    while number_removed <= number_to_remove:
        # create a random coordinate and check to see if the unit qualifies for removal
        ranx = random.randint(0, 8)
        rany = random.randint(0, 8)

        if new_grid[rany][ranx] != 0 and unit_count(new_grid, new_grid[rany][ranx]) > 1:
            # if the unit has not been removed already or appears more than once in the puzzle, create a mirror of
            # that coordinate and remove the unit
            mirror_ranx = abs(ranx - 8)
            mirror_rany = abs(rany - 8)

            new_grid[rany][ranx] = 0
            number_removed += 1
            # check if mirror has been removed. If not, remove.
            if new_grid[mirror_rany][mirror_ranx] != 0 and unit_count(new_grid, new_grid[mirror_rany][mirror_ranx]) > 1:
                new_grid[mirror_rany][mirror_ranx] = 0
                number_removed += 1

    return new_grid


# unit_count checks the number of times the specified number appears in the puzzle. returns an int
def unit_count(puzzle, unit):
    count = 0
    for x in range(9):
        for y in range(9):
            if unit == puzzle[y][x]:
                count += 1
    return count
