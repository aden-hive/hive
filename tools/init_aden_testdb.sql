-- ============================================================================
-- AdenTestDB Database Initialization Script
-- ============================================================================
-- Purpose: Create a professional testing database for Aden Hive MSSQL tool
-- Author: Database Architect
-- Date: 2026-02-08
-- ============================================================================

USE master;
GO

-- Drop database if exists (for clean recreation)
IF EXISTS (SELECT name FROM sys.databases WHERE name = N'AdenTestDB')
BEGIN
    ALTER DATABASE AdenTestDB SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE AdenTestDB;
    PRINT 'Existing AdenTestDB dropped successfully.';
END
GO

-- Create new database
CREATE DATABASE AdenTestDB;
GO

PRINT 'AdenTestDB created successfully.';
GO

USE AdenTestDB;
GO

-- ============================================================================
-- TABLE: Departments
-- ============================================================================
-- Purpose: Store department information with budget tracking
-- ============================================================================

CREATE TABLE Departments (
    department_id   INT IDENTITY(1,1) NOT NULL,
    name            NVARCHAR(100) NOT NULL,
    budget          DECIMAL(15,2) NOT NULL,
    created_date    DATETIME NOT NULL DEFAULT GETDATE(),

    CONSTRAINT PK_Departments PRIMARY KEY (department_id),
    CONSTRAINT UK_Departments_Name UNIQUE (name),
    CONSTRAINT CK_Departments_Budget CHECK (budget >= 0)
);
GO

-- Create index for performance optimization
CREATE INDEX IX_Departments_Name ON Departments(name);
GO

PRINT 'Departments table created successfully.';
GO

-- ============================================================================
-- TABLE: Employees
-- ============================================================================
-- Purpose: Store employee information with department association
-- ============================================================================

CREATE TABLE Employees (
    employee_id     INT IDENTITY(1000,1) NOT NULL,
    first_name      NVARCHAR(50) NOT NULL,
    last_name       NVARCHAR(50) NOT NULL,
    email           NVARCHAR(100) NOT NULL,
    salary          DECIMAL(12,2) NOT NULL,
    hire_date       DATETIME NOT NULL,
    department_id   INT NOT NULL,

    CONSTRAINT PK_Employees PRIMARY KEY (employee_id),
    CONSTRAINT UK_Employees_Email UNIQUE (email),
    CONSTRAINT CK_Employees_Salary CHECK (salary >= 0),
    CONSTRAINT FK_Employees_Departments
        FOREIGN KEY (department_id) REFERENCES Departments(department_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);
GO

-- Create indexes for performance optimization
CREATE INDEX IX_Employees_DepartmentId ON Employees(department_id);
CREATE INDEX IX_Employees_LastName ON Employees(last_name);
CREATE INDEX IX_Employees_Email ON Employees(email);
GO

PRINT 'Employees table created successfully.';
GO

-- ============================================================================
-- SAMPLE DATA: Departments
-- ============================================================================

INSERT INTO Departments (name, budget, created_date) VALUES
    ('Engineering', 2500000.00, '2023-01-15'),
    ('Human Resources', 800000.00, '2023-01-15'),
    ('Sales', 1500000.00, '2023-01-20'),
    ('Marketing', 1200000.00, '2023-02-01'),
    ('Finance', 1000000.00, '2023-02-10');
GO

PRINT 'Sample departments inserted successfully.';
GO

-- ============================================================================
-- SAMPLE DATA: Employees
-- ============================================================================

INSERT INTO Employees (first_name, last_name, email, salary, hire_date, department_id) VALUES
    -- Engineering Department (ID: 1)
    ('John', 'Smith', 'john.smith@adenhive.com', 120000.00, '2023-03-01', 1),
    ('Sarah', 'Johnson', 'sarah.johnson@adenhive.com', 115000.00, '2023-03-15', 1),
    ('Michael', 'Chen', 'michael.chen@adenhive.com', 125000.00, '2023-04-01', 1),
    ('Emily', 'Rodriguez', 'emily.rodriguez@adenhive.com', 110000.00, '2023-05-10', 1),
    ('David', 'Kim', 'david.kim@adenhive.com', 105000.00, '2024-01-15', 1),

    -- Human Resources Department (ID: 2)
    ('Lisa', 'Anderson', 'lisa.anderson@adenhive.com', 85000.00, '2023-02-20', 2),
    ('James', 'Wilson', 'james.wilson@adenhive.com', 80000.00, '2023-06-01', 2),

    -- Sales Department (ID: 3)
    ('Jennifer', 'Taylor', 'jennifer.taylor@adenhive.com', 95000.00, '2023-04-15', 3),
    ('Robert', 'Martinez', 'robert.martinez@adenhive.com', 90000.00, '2023-05-01', 3),
    ('Amanda', 'Garcia', 'amanda.garcia@adenhive.com', 92000.00, '2023-07-20', 3),

    -- Marketing Department (ID: 4)
    ('Christopher', 'Lee', 'christopher.lee@adenhive.com', 88000.00, '2023-03-10', 4),
    ('Michelle', 'White', 'michelle.white@adenhive.com', 86000.00, '2023-08-01', 4),
    ('Kevin', 'Brown', 'kevin.brown@adenhive.com', 84000.00, '2024-02-01', 4),

    -- Finance Department (ID: 5)
    ('Jessica', 'Davis', 'jessica.davis@adenhive.com', 98000.00, '2023-02-15', 5),
    ('Daniel', 'Miller', 'daniel.miller@adenhive.com', 95000.00, '2023-09-01', 5);
GO

PRINT 'Sample employees inserted successfully.';
GO

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

PRINT '';
PRINT '============================================================';
PRINT 'Database Setup Summary';
PRINT '============================================================';

-- Count departments
DECLARE @DeptCount INT;
SELECT @DeptCount = COUNT(*) FROM Departments;
PRINT 'Total Departments: ' + CAST(@DeptCount AS NVARCHAR(10));

-- Count employees
DECLARE @EmpCount INT;
SELECT @EmpCount = COUNT(*) FROM Employees;
PRINT 'Total Employees: ' + CAST(@EmpCount AS NVARCHAR(10));

-- Show department summary
PRINT '';
PRINT 'Department Summary:';
PRINT '------------------------------------------------------------';
SELECT
    d.name AS Department,
    COUNT(e.employee_id) AS Employees,
    d.budget AS Budget,
    FORMAT(d.budget / NULLIF(COUNT(e.employee_id), 0), 'C', 'en-US') AS BudgetPerEmployee
FROM Departments d
LEFT JOIN Employees e ON d.department_id = e.department_id
GROUP BY d.name, d.budget
ORDER BY d.name;
GO

PRINT '';
PRINT '============================================================';
PRINT 'AdenTestDB initialization completed successfully!';
PRINT '============================================================';
PRINT '';
PRINT 'Next Steps:';
PRINT '1. Run: python test_mssql_connection.py';
PRINT '2. Verify JOIN queries work correctly';
PRINT '3. Test relational integrity';
PRINT '============================================================';
GO
