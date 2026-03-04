# BFSI Personal Loan Automation Agent

## Overview
This directory contains a multi agent system built on the Aden Hive framework designed to automate the personal loan approval process for the BFSI sector. 

## Architecture
This system utilizes the Queen Bee and Worker Bee architecture to distribute complex financial tasks:
* Queen Bee (Orchestrator): Manages the application intake and routes tasks to the appropriate specialists.
* KYC Worker Bee: Specialized in extracting and verifying identity documents.
* Credit Worker Bee: Specialized in analyzing financial history to generate a risk score.

## Current Status
This initial merge request establishes the graph workflow and agent delegation structure. Future updates will integrate the full AI evaluation logic for document processing.