"""Main entry point for Orbitron Kernel."""

from kernel import OrbitronKernel


def main():
    """Main function."""
    kernel = OrbitronKernel()
    prompt = (
        "Create a markdown file named 'test.md' with the content '# Hallo Welt'. "
        "Then update the same file so it becomes:\n\n"
        "# Hallo Welt\n\nDies ist ein Test.\n"
    )
    response = kernel.assist(prompt)
    print(response)


if __name__ == "__main__":
    main()
