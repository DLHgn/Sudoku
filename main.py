import generator

grid = generator.generate_grid()
print(*grid, sep="\n")
new_puzzle = generator.create_puzzle(grid, 50)
print("\n", *new_puzzle, sep="\n")